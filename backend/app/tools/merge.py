"""Merge several PDFs into one, in the order they were uploaded."""
from __future__ import annotations

from contextlib import ExitStack

import pikepdf

from app.tools.base import OutputFile, ToolContext, ToolError, ToolResult
from app.tools.pdfutil import PDF_MIME, make_meta, open_pdf, save_pdf


def _passwords(ctx: ToolContext) -> list[str]:
    count = len(ctx.inputs)
    raw = ctx.options.get("passwords")
    if raw is None:
        return [""] * count
    if not isinstance(raw, list) or len(raw) > count:
        raise ToolError("invalid_options", "The option 'passwords' must be a list with one entry per file.")
    values: list[str] = []
    for item in raw:
        if item is None:
            values.append("")
        elif isinstance(item, str) and len(item) <= 256:
            values.append(item)
        else:
            raise ToolError("invalid_options", "The option 'passwords' must contain text or null.")
    values.extend([""] * (count - len(values)))
    return values


def run(ctx: ToolContext) -> ToolResult:
    passwords = _passwords(ctx)
    count = len(ctx.inputs)
    dest = ctx.out_path("merged.pdf")

    with ExitStack() as stack:
        merged = stack.enter_context(pikepdf.Pdf.new())
        for number, item in enumerate(ctx.inputs):
            source = stack.enter_context(
                open_pdf(item.path, passwords[number], label=f"file {number + 1}")
            )
            merged.pages.extend(source.pages)
            ctx.progress(5 + 75 * (number + 1) // count)
        total = len(merged.pages)
        ctx.progress(85)
        save_pdf(merged, dest)  # sources must stay open until here

    return ToolResult(
        outputs=[OutputFile(dest, "merged.pdf", PDF_MIME)],
        meta=make_meta(ctx, [dest], total, total),
    )
