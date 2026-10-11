"""Add page numbers to all or selected pages (Helvetica, works on rotated pages)."""
from __future__ import annotations

import pymupdf

from app.tools.base import ToolContext, ToolResult
from app.tools.mupdf import open_doc, parse_color, save_doc, text_width
from app.tools.pagespec import parse_pages, unique
from app.tools.pdfutil import get_password, pages_option, single_result

POSITIONS = (
    "bottom-center",
    "bottom-right",
    "bottom-left",
    "top-center",
    "top-right",
    "top-left",
)
FORMATS = ("n", "page_n", "n_of_total", "page_n_of_total")


def label_for(fmt: str, number: int, last: int) -> str:
    if fmt == "page_n":
        return f"Page {number}"
    if fmt == "n_of_total":
        return f"{number} of {last}"
    if fmt == "page_n_of_total":
        return f"Page {number} of {last}"
    return str(number)


def anchor(rect: pymupdf.Rect, position: str, margin: float, size: float, width: float) -> pymupdf.Point:
    """Start of the text baseline on the page as it appears on screen."""
    vertical, horizontal = position.split("-")
    if horizontal == "left":
        x = rect.x0 + margin
    elif horizontal == "right":
        x = rect.x1 - margin - width
    else:
        x = (rect.x0 + rect.x1 - width) / 2
    y = rect.y1 - margin if vertical == "bottom" else rect.y0 + margin + size
    return pymupdf.Point(max(x, rect.x0), y)


def run(ctx: ToolContext) -> ToolResult:
    item = ctx.inputs[0]
    position = ctx.opt_str("position", "bottom-center", allowed=POSITIONS)
    fmt = ctx.opt_str("format", "n", allowed=FORMATS)
    start = ctx.opt_int("start", 1, minimum=0, maximum=1_000_000)
    size = ctx.opt_int("font_size", 11, minimum=6, maximum=48)
    margin = ctx.opt_int("margin", 30, minimum=0, maximum=200)
    color = parse_color(ctx.opt_str("color", "#000000", max_len=16))
    dest = ctx.out_path("numbered.pdf")

    with open_doc(item.path, get_password(ctx)) as doc:
        total = doc.page_count
        indices = unique(parse_pages(pages_option(ctx, "pages", "all"), total))
        last = start + len(indices) - 1
        for count, index in enumerate(indices):
            page = doc.load_page(index)
            text = label_for(fmt, start + count, last)
            width = text_width(text, float(size))
            point = anchor(page.rect, position, float(margin), float(size), width) * page.derotation_matrix
            page.insert_text(
                point,
                text,
                fontsize=size,
                fontname="helv",
                color=color,
                fill=color,
                rotate=page.rotation,
            )
            ctx.progress(10 + 75 * (count + 1) // len(indices))
        ctx.progress(88)
        save_doc(doc, dest)

    return single_result(ctx, dest, "numbered", total, total)
