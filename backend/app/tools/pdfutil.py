"""Helpers shared by the page tools. Imports pikepdf: import this only from tool modules (worker)."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pikepdf

from app.tools.base import OutputFile, ToolContext, ToolError, ToolResult

PDF_MIME = "application/pdf"


def open_pdf(path: Path, password: str = "", label: str = "this PDF") -> pikepdf.Pdf:
    """Open a PDF; map password problems to friendly errors. Other failures map via map_exception."""
    try:
        pdf = pikepdf.open(path, password=password)
    except pikepdf.PasswordError as exc:
        if password:
            raise ToolError("wrong_password", f"The password for {label} is incorrect.") from exc
        first = label[:1].upper() + label[1:]
        raise ToolError(
            "password_required",
            f"{first} is password-protected. Enter its password to continue.",
        ) from exc
    if len(pdf.pages) == 0:
        pdf.close()
        raise ToolError("corrupted_file")
    return pdf


def get_password(ctx: ToolContext, key: str = "password") -> str:
    value = ctx.options.get(key)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 256:
        raise ToolError("invalid_options", "The password must be text.")
    return value


def pages_option(ctx: ToolContext, key: str, default: str | None = None) -> str:
    """A page selection given as text ('1-3,5') or as a JSON list of page numbers."""
    value = ctx.options.get(key, default)
    if (
        isinstance(value, list)
        and len(value) <= 10_000
        and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    ):
        value = ",".join(str(v) for v in value)
    if not isinstance(value, str) or not value.strip() or len(value) > 60_000:
        raise ToolError("invalid_options", f"Enter the pages for '{key}', for example 1-3,5.")
    return value


def opt_float(
    ctx: ToolContext,
    key: str,
    default: float | None = None,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value: Any = ctx.options.get(key, default)
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            value = None
    if (
        value is None
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ToolError("invalid_options", f"The option '{key}' must be a number.")
    value = float(value)
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise ToolError("invalid_options", f"The option '{key}' is out of range.")
    return value


def copy_pages(source: pikepdf.Pdf, indices: list[int]) -> pikepdf.Pdf:
    """A brand-new PDF holding the given source pages (0-based) in the given order."""
    result = pikepdf.Pdf.new()
    try:
        for index in indices:
            result.pages.append(source.pages[index])
    except BaseException:
        result.close()
        raise
    return result


def save_pdf(pdf: pikepdf.Pdf, dest: Path) -> None:
    pdf.save(dest, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)


def out_name(stem: str, suffix: str) -> str:
    return f"{stem[:80] or 'file'}_{suffix}.pdf"


def make_meta(ctx: ToolContext, outputs: list[Path], pages_in: int, pages_out: int) -> dict[str, Any]:
    return {
        "pages_in": pages_in,
        "pages_out": pages_out,
        "input_bytes": sum(item.path.stat().st_size for item in ctx.inputs),
        "output_bytes": sum(path.stat().st_size for path in outputs),
    }


def single_result(ctx: ToolContext, dest: Path, suffix: str, pages_in: int, pages_out: int) -> ToolResult:
    name = out_name(ctx.inputs[0].stem, suffix)
    return ToolResult(
        outputs=[OutputFile(dest, name, PDF_MIME)],
        meta=make_meta(ctx, [dest], pages_in, pages_out),
    )
