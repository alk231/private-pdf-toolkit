"""Worker process: python -m app.worker

Protocol with the API process:
  * stdin  : ONE JSON document, the job spec. It stays in memory only, so options such as
             passwords are never written to disk and never appear in argv.
  * stdout : a private channel of lines, "PROGRESS <0-99>" and finally "RESULT <json>".
             fd 1 is redirected to /dev/null right after start so that libraries and child
             processes (Ghostscript, qpdf, ...) can never corrupt or fake the channel.
  * stderr : ignored by the parent (nothing is logged, so file names cannot leak).
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

from app.tools.base import InputFile, ToolContext, ToolError, ToolResult, map_exception
from app.tools.catalog import get_tool

class _Channel:
    def __init__(self) -> None:
        self._out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
        null_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null_fd, 1)
        os.close(null_fd)
        self._last = -1

    def _send(self, tag: str, payload: str) -> None:
        try:
            self._out.write(f"{tag} {payload}\n")
            self._out.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def progress(self, pct: int) -> None:
        pct = max(0, min(int(pct), 99))
        if pct > self._last:
            self._last = pct
            self._send("PROGRESS", str(pct))

    def result(self, payload: dict) -> None:
        self._send("RESULT", json.dumps(payload, default=str, separators=(",", ":")))

def _apply_limits(limits: dict) -> None:
    """Hard resource limits for this process; child processes inherit them."""
    try:
        import resource
    except ImportError:  # not Linux; the backend targets Linux/Docker
        return

    def _set(which: int, soft: int, hard: int | None = None) -> None:
        try:
            resource.setrlimit(which, (soft, soft if hard is None else hard))
        except (ValueError, OSError):
            pass

    memory_mb = int(limits.get("memory_mb") or 0)
    if memory_mb > 0:
        _set(resource.RLIMIT_AS, memory_mb * 1024 * 1024)
    output_mb = int(limits.get("max_output_mb") or 0)
    if output_mb > 0:
        _set(resource.RLIMIT_FSIZE, output_mb * 1024 * 1024)
    cpu_sec = int(limits.get("cpu_sec") or 0)
    if cpu_sec > 0:
        _set(resource.RLIMIT_CPU, cpu_sec, cpu_sec + 5)
    _set(resource.RLIMIT_CORE, 0)

def _validated_outputs(result: ToolResult, out_dir: Path) -> list[dict]:
    if not result.outputs:
        raise ToolError("processing_failed")
    root = out_dir.resolve()
    items: list[dict] = []
    for out in result.outputs:
        path = Path(out.path).resolve()
        if not path.is_file() or root not in path.parents:
            raise ToolError("processing_failed")
        items.append({"path": str(path), "name": out.name, "mime": out.mime})
    return items

def main() -> int:
    chan = _Channel()
    try:
        spec = json.loads(sys.stdin.read())
        if not isinstance(spec, dict):
            raise ValueError("spec must be an object")
    except Exception:
        chan.result({"ok": False, "code": "processing_failed", "message": ""})
        return 1

    limits = spec.get("limits") or {}
    _apply_limits(limits)

    try:
        tool = get_tool(str(spec.get("tool", "")), include_internal=True)
        if tool is None:
            raise ToolError("processing_failed")
        out_dir = Path(spec["out_dir"])
        ctx = ToolContext(
            tool=tool.name,
            inputs=[InputFile(Path(i["path"]), str(i["name"]), str(i["kind"])) for i in spec["inputs"]],
            options=spec.get("options") or {},
            out_dir=out_dir,
            tmp_dir=Path(spec["tmp_dir"]),
            limits=limits,
            progress_cb=chan.progress,
        )
        module = importlib.import_module(tool.module)
        result = module.run(ctx)
        outputs = _validated_outputs(result, out_dir)
        chan.result(
            {"ok": True, "outputs": outputs, "meta": result.meta, "zip_name": result.zip_name}
        )
        return 0
    except BaseException as exc:  # noqa: BLE001 - includes MemoryError; always report cleanly
        err = map_exception(exc)
        chan.result({"ok": False, "code": err.code, "message": err.message})
        return 0

if __name__ == "__main__":
    sys.exit(main())
