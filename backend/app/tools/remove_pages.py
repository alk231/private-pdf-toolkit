"""Remove chosen pages and keep the rest."""
from __future__ import annotations

from app.tools.base import ToolContext, ToolError, ToolResult
from app.tools.pagespec import parse_pages
from app.tools.pdfutil import copy_pages, get_password, open_pdf, pages_option, save_pdf, single_result


def run(ctx: ToolContext) -> ToolResult:
    item = ctx.inputs[0]
    dest = ctx.out_path("edited.pdf")

    with open_pdf(item.path, get_password(ctx)) as source:
        total = len(source.pages)
        removed = set(parse_pages(pages_option(ctx, "pages"), total))
        keep = [index for index in range(total) if index not in removed]
        if not keep:
            raise ToolError("invalid_options", "You can't remove every page. Keep at least one page.")
        ctx.progress(20)
        with copy_pages(source, keep) as result:
            ctx.progress(70)
            save_pdf(result, dest)

    return single_result(ctx, dest, "pages_removed", total, len(keep))
