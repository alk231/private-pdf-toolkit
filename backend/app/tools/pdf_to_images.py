"""Render PDF pages to JPG or PNG images (several images are returned as a zip)."""
from __future__ import annotations

import math

import pymupdf

from app.tools.base import OutputFile, ToolContext, ToolError, ToolResult
from app.tools.mupdf import open_doc
from app.tools.pagespec import parse_pages, unique
from app.tools.pdfutil import get_password, make_meta, pages_option

MAX_IMAGES = 150
MAX_PIXELS = 30_000_000  # per page; the DPI is lowered for huge pages


def run(ctx: ToolContext) -> ToolResult:
    item = ctx.inputs[0]
    fmt = ctx.opt_str("format", "jpg", allowed=("jpg", "png"))
    dpi = ctx.opt_int("dpi", 150, minimum=72, maximum=300)
    quality = ctx.opt_int("quality", 85, minimum=30, maximum=95)
    gray = ctx.opt_bool("grayscale", False)
    colorspace = pymupdf.csGRAY if gray else pymupdf.csRGB
    mime = "image/jpeg" if fmt == "jpg" else "image/png"
    output_format = "jpeg" if fmt == "jpg" else "png"

    outputs: list[OutputFile] = []
    with open_doc(item.path, get_password(ctx)) as doc:
        total = doc.page_count
        indices = unique(parse_pages(pages_option(ctx, "pages", "all"), total))
        if len(indices) > MAX_IMAGES:
            raise ToolError(
                "invalid_options",
                f"You can convert up to {MAX_IMAGES} pages at a time. Choose a smaller page range.",
            )

        stem = item.stem[:80]
        width = len(str(total))
        for count, index in enumerate(indices, start=1):
            page = doc.load_page(index)
            rect = page.rect
            zoom = dpi / 72.0
            pixels = (rect.width * zoom) * (rect.height * zoom)
            if pixels > MAX_PIXELS:
                zoom *= math.sqrt(MAX_PIXELS / pixels)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=colorspace, alpha=False)
            dest = ctx.out_path(f"page_{count:04d}.{fmt}")
            pix.save(str(dest), output=output_format, jpg_quality=quality)
            del pix
            outputs.append(OutputFile(dest, f"{stem}_page{str(index + 1).zfill(width)}.{fmt}", mime))
            ctx.progress(5 + 90 * count // len(indices))

    meta = make_meta(ctx, [o.path for o in outputs], total, len(outputs))
    meta["dpi"] = dpi
    meta["format"] = fmt
    return ToolResult(outputs=outputs, meta=meta, zip_name=f"{stem}_images.zip")
