"""Shared tool framework: context, results, errors. Light imports only (used by API and worker)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.errors import USER_MESSAGES

class ToolError(Exception):
    """Raise from a tool to fail the job with a friendly, machine-readable error."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message or USER_MESSAGES.get(code, USER_MESSAGES["processing_failed"])

@dataclass(frozen=True)
class InputFile:
    path: Path  # on-disk copy, e.g. .../in/f0.pdf (never the user's file name)
    name: str  # sanitised original name; only for naming outputs. Never log it.
    kind: str  # "pdf" | "image" | ...

    @property
    def stem(self) -> str:
        return Path(self.name).stem or "file"

@dataclass(frozen=True)
class OutputFile:
    path: Path  # must be inside ctx.out_dir
    name: str  # download name
    mime: str

@dataclass
class ToolResult:
    outputs: list[OutputFile]
    meta: dict[str, Any] = field(default_factory=dict)  # small JSON-safe facts, e.g. sizes
    zip_name: str | None = None  # name of the zip when there are several outputs

def _noop(_pct: int) -> None:
    return None

@dataclass
class ToolContext:
    tool: str
    inputs: list[InputFile]
    options: dict[str, Any]
    out_dir: Path
    tmp_dir: Path
    limits: dict[str, Any] = field(default_factory=dict)
    progress_cb: Callable[[int], None] = _noop

    def progress(self, pct: int) -> None:
        """Report progress 0..99 (100 is set automatically when the job is done)."""
        try:
            self.progress_cb(int(pct))
        except Exception:
            pass

    def out_path(self, name: str) -> Path:
        return self.out_dir / name

    # ---- option helpers: raise ToolError("invalid_options") on bad input ----

    def opt_int(
        self,
        key: str,
        default: int | None = None,
        *,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int:
        value = self.options.get(key, default)
        if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
            value = int(value.strip())
        if value is None or isinstance(value, bool) or not isinstance(value, int):
            raise ToolError("invalid_options", f"The option '{key}' must be a whole number.")
        if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
            raise ToolError("invalid_options", f"The option '{key}' is out of range.")
        return value

    def opt_str(
        self,
        key: str,
        default: str | None = None,
        *,
        allowed: tuple[str, ...] | None = None,
        max_len: int = 500,
    ) -> str:
        value = self.options.get(key, default)
        if not isinstance(value, str):
            raise ToolError("invalid_options", f"The option '{key}' must be text.")
        if len(value) > max_len:
            raise ToolError("invalid_options", f"The option '{key}' is too long.")
        if allowed is not None and value not in allowed:
            raise ToolError("invalid_options", f"The option '{key}' has an unsupported value.")
        return value

    def opt_bool(self, key: str, default: bool = False) -> bool:
        value = self.options.get(key, default)
        if not isinstance(value, bool):
            raise ToolError("invalid_options", f"The option '{key}' must be true or false.")
        return value

_PASSWORD_ERRORS = {"PasswordError"}
_CORRUPT_ERRORS = {"PdfError", "FileDataError", "EmptyFileError", "FzErrorFormat", "UnidentifiedImageError"}
_COMPLEX_ERRORS = {"DecompressionBombError", "MemoryError", "RecursionError"}

def map_exception(exc: BaseException) -> ToolError:
    """Turn any exception into a ToolError without importing the libraries that raised it."""
    if isinstance(exc, ToolError):
        return exc
    names = {cls.__name__ for cls in type(exc).__mro__}
    if names & _PASSWORD_ERRORS:
        return ToolError("wrong_password")
    if names & _COMPLEX_ERRORS:
        return ToolError("too_complex")
    if names & _CORRUPT_ERRORS:
        return ToolError("corrupted_file")
    return ToolError("processing_failed")
