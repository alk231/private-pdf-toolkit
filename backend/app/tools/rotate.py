"""Rotate all or selected pages clockwise (adds to any existing rotation)."""
from __future__ import annotations

from app.tools.base import ToolContext, ToolError, ToolResult
from app.tools.pagespec import parse_pages, unique
from app.tools.pdfutil import get_password, open_pdf, pages_option, save_pdf, single_result


def run(ctx: ToolContext) -> ToolResult:
    item = ctx.inputs[0]
    dest = ctx.out_path("rotated.pdf")

    angle = ctx.opt_int("angle", 90, minimum=-360, maximum=360)
    if angle % 90 != 0 or angle % 360 == 0:
        raise ToolError("invalid_options", "Choose a rotation of 90, 180 or 270 degrees.")
    angle %= 360

    with open_pdf(item.path, get_password(ctx)) as pdf:
        total = len(pdf.pages)
        indices = unique(parse_pages(pages_option(ctx, "pages", "all"), total))
        ctx.progress(30)
        for index in indices:
            pdf.pages[index].rotate(angle, True)
        ctx.progress(70)
        save_pdf(pdf, dest)

    return single_result(ctx, dest, "rotated", total, total)
