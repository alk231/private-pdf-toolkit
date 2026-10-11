"""Remove the password and restrictions from a PDF (the password is needed if the PDF asks for one to open)."""
from __future__ import annotations

import pikepdf

from app.tools.base import ToolContext, ToolResult
from app.tools.pdfutil import get_password, open_pdf, single_result


def run(ctx: ToolContext) -> ToolResult:
    item = ctx.inputs[0]
    dest = ctx.out_path("unlocked.pdf")

    with open_pdf(item.path, get_password(ctx)) as pdf:
        was_encrypted = bool(pdf.is_encrypted)
        total = len(pdf.pages)
        ctx.progress(40)
        pdf.save(
            dest,
            encryption=False,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )

    result = single_result(ctx, dest, "unlocked", total, total)
    result.meta["was_encrypted"] = was_encrypted
    return result
