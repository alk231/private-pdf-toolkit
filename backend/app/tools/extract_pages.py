"""Extract chosen pages into a new PDF (in the order written; duplicates are ignored)."""
from __future__ import annotations

from app.tools.base import ToolContext, ToolResult
from app.tools.pagespec import parse_pages, unique
from app.tools.pdfutil import copy_pages, get_password, open_pdf, pages_option, save_pdf, single_result


def run(ctx: ToolContext) -> ToolResult:
    item = ctx.inputs[0]
    dest = ctx.out_path("extracted.pdf")

    with open_pdf(item.path, get_password(ctx)) as source:
        total = len(source.pages)
        indices = unique(parse_pages(pages_option(ctx, "pages"), total))
        ctx.progress(20)
        with copy_pages(source, indices) as result:
            ctx.progress(70)
            save_pdf(result, dest)

    return single_result(ctx, dest, "extracted", total, len(indices))
