"""Shrink a PDF with Ghostscript and report the size before and after.

If Ghostscript cannot make the file smaller, the original is returned and meta.already_optimized is true.
Password-protected input is decrypted with pikepdf first, so a password never appears on a command line.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from app.tools.base import ToolContext, ToolError, ToolResult
from app.tools.pdfutil import get_password, open_pdf, single_result

LEVELS = ("screen", "ebook", "printer")


def _ghostscript(source: Path, dest: Path, level: str, tmp_dir: Path, timeout: float) -> None:
    gs = shutil.which("gs")
    if gs is None:
        raise ToolError("processing_failed", "Compression is not available on this server right now.")
    command = [
        gs,
        "-q",
        "-dNOPAUSE",
        "-dBATCH",
        "-dSAFER",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.5",
        f"-dPDFSETTINGS=/{level}",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dNumRenderingThreads=1",
        f"-sOutputFile={dest}",
        str(source),
    ]
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "TMPDIR": str(tmp_dir),
        "HOME": str(tmp_dir),
        "LC_ALL": "C",
    }
    try:
        proc = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(tmp_dir),
            env=env,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        dest.unlink(missing_ok=True)
        raise ToolError("job_timeout") from exc
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise ToolError("processing_failed", "This PDF could not be compressed.")


def run(ctx: ToolContext) -> ToolResult:
    item = ctx.inputs[0]
    level = ctx.opt_str("level", "ebook", allowed=LEVELS)
    password = get_password(ctx)
    dest = ctx.out_path("compressed.pdf")

    with open_pdf(item.path, password) as pdf:
        total = len(pdf.pages)
        source = item.path
        if pdf.is_encrypted:
            source = ctx.tmp_dir / "decrypted.pdf"
            pdf.save(source, encryption=False)
    ctx.progress(15)

    work = ctx.tmp_dir / "gs_out.pdf"
    timeout = float(ctx.limits.get("job_timeout_sec", 300))
    _ghostscript(source, work, level, ctx.tmp_dir, timeout)
    ctx.progress(90)

    already_optimized = work.stat().st_size >= source.stat().st_size
    if already_optimized:
        work.unlink(missing_ok=True)
        shutil.copyfile(source, dest)
    else:
        os.replace(work, dest)

    result = single_result(ctx, dest, "compressed", total, total)
    before = int(result.meta["input_bytes"])
    after = int(result.meta["output_bytes"])
    saved = max(0, before - after)
    result.meta.update(
        {
            "level": level,
            "already_optimized": already_optimized,
            "saved_bytes": saved,
            "saved_percent": round(100.0 * saved / before, 1) if before else 0.0,
        }
    )
    return result
