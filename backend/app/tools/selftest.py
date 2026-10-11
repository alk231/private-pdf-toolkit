"""Test-only tools used to verify the job pipeline (disabled unless ENABLE_SELFTEST_TOOLS=1)."""
from __future__ import annotations

import os
import shutil
import time

from app.tools.base import OutputFile, ToolContext, ToolError, ToolResult

_PDF = "application/pdf"

def run(ctx: ToolContext) -> ToolResult:
    first = ctx.inputs[0]

    if ctx.tool == "selftest-copy":
        dest = ctx.out_path("copy.pdf")
        ctx.progress(20)
        shutil.copyfile(first.path, dest)
        ctx.progress(80)
        return ToolResult(
            outputs=[OutputFile(dest, f"{first.stem}_copy.pdf", _PDF)],
            meta={"input_bytes": first.path.stat().st_size, "output_bytes": dest.stat().st_size},
        )

    if ctx.tool == "selftest-multi":
        one = ctx.out_path("one.pdf")
        two = ctx.out_path("two.pdf")
        shutil.copyfile(first.path, one)
        shutil.copyfile(first.path, two)
        return ToolResult(
            outputs=[OutputFile(one, "part-1.pdf", _PDF), OutputFile(two, "part-2.pdf", _PDF)],
            zip_name="parts.zip",
        )

    if ctx.tool == "selftest-fail":
        raise ToolError("wrong_password")

    if ctx.tool == "selftest-sleep":
        seconds = ctx.opt_int("seconds", 1, minimum=0, maximum=600)
        ctx.progress(10)
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            time.sleep(0.05)
        dest = ctx.out_path("slept.pdf")
        shutil.copyfile(first.path, dest)
        return ToolResult(outputs=[OutputFile(dest, "slept.pdf", _PDF)])

    if ctx.tool == "selftest-crash":
        os._exit(3)  # simulate a hard crash with no result

    raise ToolError("processing_failed")
