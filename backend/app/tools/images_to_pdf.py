"""Turn images (JPG, PNG, WebP, GIF, BMP, TIFF) into one PDF: one image per page, in upload order.

Images are shrunk to a sensible size and stored as JPEG to keep the PDF small. Transparent areas become white.
Animated GIFs and multi-page TIFFs use their first frame.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

from app.tools.base import OutputFile, ToolContext, ToolError, ToolResult
from app.tools.pdfutil import PDF_MIME, make_meta

Image.MAX_IMAGE_PIXELS = 40_000_000  # warns above this, refuses above twice this

PAGE_SIZES = {"a4": (595.0, 842.0), "letter": (612.0, 792.0)}  # portrait, points
QUALITY = {"high": (3508, 90), "medium": (2480, 80), "low": (1654, 65)}  # (longest side px, JPEG quality)
FIT_LONG_SIDE = 842.0
MIN_PAGE = 36.0
MAX_PAGE = 14000.0


def layout(
    width_px: int,
    height_px: int,
    size: str,
    orientation: str,
    margin: float,
) -> tuple[float, float, tuple[float, float, float, float]]:
    """Return (page_width, page_height, (x0, y0, x1, y1) of the image) in points."""
    if size == "fit":
        scale = min(1.0, FIT_LONG_SIDE / max(width_px, height_px))
        draw_w, draw_h = width_px * scale, height_px * scale
        page_w = min(max(draw_w + 2 * margin, MIN_PAGE), MAX_PAGE)
        page_h = min(max(draw_h + 2 * margin, MIN_PAGE), MAX_PAGE)
    else:
        base_w, base_h = PAGE_SIZES[size]
        if orientation == "auto":
            landscape = width_px > height_px
        else:
            landscape = orientation == "landscape"
        page_w, page_h = (base_h, base_w) if landscape else (base_w, base_h)
        avail_w = max(page_w - 2 * margin, 1.0)
        avail_h = max(page_h - 2 * margin, 1.0)
        scale = min(avail_w / width_px, avail_h / height_px)
        draw_w, draw_h = width_px * scale, height_px * scale
    x0 = (page_w - draw_w) / 2
    y0 = (page_h - draw_h) / 2
    return page_w, page_h, (x0, y0, x0 + draw_w, y0 + draw_h)


def _flatten(image: Image.Image) -> Image.Image:
    mode = image.mode
    if mode in ("RGB", "L"):
        return image
    if mode in ("RGBA", "LA", "PA") or (mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    if mode == "1":
        return image.convert("L")
    if mode in ("I", "I;16", "I;16L", "I;16B", "F"):
        return image.convert("I").point(lambda value: value * (1 / 256)).convert("L")
    return image.convert("RGB")


def _prepare(src: Path, dest: Path, max_side: int, quality: int) -> tuple[int, int]:
    """Decode, shrink, fix orientation, flatten and save as JPEG. Returns the pixel size."""
    with Image.open(src) as opened:
        opened.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)  # JPEGs are decoded at reduced size
        try:
            upright = ImageOps.exif_transpose(opened)
        except Exception:
            upright = opened
        flat = _flatten(upright)
        flat.save(dest, "JPEG", quality=quality, optimize=True)
        return flat.size


def run(ctx: ToolContext) -> ToolResult:
    size = ctx.opt_str("page_size", "a4", allowed=("fit", "a4", "letter"))
    orientation = ctx.opt_str("orientation", "auto", allowed=("auto", "portrait", "landscape"))
    margin = ctx.opt_int("margin", 0 if size == "fit" else 24, minimum=0, maximum=144)
    quality_name = ctx.opt_str("quality", "medium", allowed=tuple(QUALITY))
    max_side, jpeg_quality = QUALITY[quality_name]

    count = len(ctx.inputs)
    dest = ctx.out_path("images.pdf")
    doc = pymupdf.open()
    try:
        for number, item in enumerate(ctx.inputs, start=1):
            prepared = ctx.tmp_dir / f"img_{number}.jpg"
            try:
                width_px, height_px = _prepare(item.path, prepared, max_side, jpeg_quality)
            except ToolError:
                raise
            except Exception as exc:
                if type(exc).__name__ in ("DecompressionBombError", "MemoryError"):
                    raise
                raise ToolError("corrupted_file", f"Image {number} could not be read.") from exc

            page_w, page_h, box = layout(width_px, height_px, size, orientation, float(margin))
            page = doc.new_page(width=page_w, height=page_h)
            page.insert_image(pymupdf.Rect(*box), filename=str(prepared), keep_proportion=False)
            ctx.progress(5 + 80 * number // count)
        ctx.progress(90)
        doc.save(str(dest), garbage=3, deflate=True)
    finally:
        doc.close()

    name = f"{ctx.inputs[0].stem[:80]}.pdf" if count == 1 else "images.pdf"
    return ToolResult(
        outputs=[OutputFile(dest, name, PDF_MIME)],
        meta=make_meta(ctx, [dest], count, count),
    )
