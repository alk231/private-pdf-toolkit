"""Add a text or image watermark to all or selected pages.

type "text": one PDF; Latin text only (Helvetica); shrinks automatically to fit the page.
type "image": one PDF plus one image (any upload order); the image keeps its transparency.
"""
from __future__ import annotations

import math
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

from app.tools.base import InputFile, OutputFile, ToolContext, ToolError, ToolResult
from app.tools.mupdf import latin_text, open_doc, parse_color, save_doc, text_width
from app.tools.pagespec import parse_pages, unique
from app.tools.pdfutil import PDF_MIME, get_password, opt_float, out_name, pages_option

Image.MAX_IMAGE_PIXELS = 40_000_000
STAMP_MAX_PX = 1600


def _apply_text(ctx: ToolContext, doc: pymupdf.Document, indices: list[int], overlay: bool) -> None:
    text = latin_text(ctx.opt_str("text", "", max_len=100))
    size = ctx.opt_int("font_size", 60, minimum=8, maximum=300)
    angle = ctx.opt_int("angle", 45, minimum=-180, maximum=180)
    opacity = opt_float(ctx, "opacity", 0.3, minimum=0.05, maximum=1.0)
    color = parse_color(ctx.opt_str("color", "#808080", max_len=16))

    unit = text_width(text, 100.0) / 100.0  # text width per point of font size
    radians = math.radians(angle)
    cos_a, sin_a = abs(math.cos(radians)), abs(math.sin(radians))

    for count, index in enumerate(indices, start=1):
        page = doc.load_page(index)
        rect = page.rect
        box_w = unit * size * cos_a + size * sin_a
        box_h = unit * size * sin_a + size * cos_a
        fit = min(1.0, 0.92 * rect.width / box_w, 0.92 * rect.height / box_h)
        effective = max(6.0, size * fit)
        width = unit * effective

        centre = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2) * page.derotation_matrix
        start = pymupdf.Point(centre.x - width / 2, centre.y + 0.35 * effective)
        turn = (angle + page.rotation) % 360
        morph = (centre, pymupdf.Matrix(float(turn))) if turn else None
        page.insert_text(
            start,
            text,
            fontsize=effective,
            fontname="helv",
            color=color,
            fill=color,
            fill_opacity=opacity,
            stroke_opacity=opacity,
            overlay=overlay,
            morph=morph,
        )
        ctx.progress(10 + 75 * count // len(indices))


def _load_stamp(path: Path, opacity: float) -> Image.Image:
    with Image.open(path) as opened:
        opened.thumbnail((STAMP_MAX_PX, STAMP_MAX_PX), Image.Resampling.LANCZOS)
        try:
            upright = ImageOps.exif_transpose(opened)
        except Exception:
            upright = opened
        rgba = upright.convert("RGBA")
    alpha = rgba.getchannel("A").point(lambda value: int(value * opacity))
    rgba.putalpha(alpha)
    return rgba


def _apply_image(
    ctx: ToolContext,
    doc: pymupdf.Document,
    indices: list[int],
    image_file: InputFile,
    overlay: bool,
) -> None:
    scale = ctx.opt_int("scale", 50, minimum=5, maximum=100)
    angle = ctx.opt_int("angle", 0, minimum=-180, maximum=180)
    opacity = opt_float(ctx, "opacity", 0.5, minimum=0.05, maximum=1.0)

    try:
        base = _load_stamp(image_file.path, opacity)
    except Exception as exc:
        if type(exc).__name__ in ("DecompressionBombError", "MemoryError"):
            raise
        raise ToolError("corrupted_file", "The watermark image could not be read.") from exc

    def turned(extra: int) -> Image.Image:
        total_angle = (angle + extra) % 360
        if not total_angle:
            return base
        return base.rotate(total_angle, resample=Image.Resampling.BICUBIC, expand=True)

    visible_w, visible_h = turned(0).size
    stamps: dict[int, Path] = {}

    def stamp_for(rotation: int) -> Path:
        if rotation not in stamps:
            path = ctx.tmp_dir / f"stamp_{rotation}.png"
            turned(rotation).save(path, "PNG")
            stamps[rotation] = path
        return stamps[rotation]

    for count, index in enumerate(indices, start=1):
        page = doc.load_page(index)
        rect = page.rect
        width = rect.width * scale / 100.0
        height = width * visible_h / visible_w
        limit = 0.95 * rect.height
        if height > limit:
            width *= limit / height
            height = limit
        cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
        visible = pymupdf.Rect(cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)
        target = visible * page.derotation_matrix
        page.insert_image(
            target,
            filename=str(stamp_for(page.rotation)),
            keep_proportion=True,
            overlay=overlay,
        )
        ctx.progress(10 + 75 * count // len(indices))


def run(ctx: ToolContext) -> ToolResult:
    kind = ctx.opt_str("type", "text", allowed=("text", "image"))
    layer = ctx.opt_str("layer", "over", allowed=("over", "under"))
    overlay = layer == "over"

    pdfs = [item for item in ctx.inputs if item.kind == "pdf"]
    images = [item for item in ctx.inputs if item.kind == "image"]
    if len(pdfs) != 1:
        raise ToolError("invalid_files", "Upload exactly one PDF to watermark.")
    if kind == "image" and len(images) != 1:
        raise ToolError("invalid_files", "Upload one PDF and one watermark image.")
    if kind == "text" and images:
        raise ToolError("invalid_files", "A text watermark needs only the PDF.")

    source = pdfs[0]
    dest = ctx.out_path("watermarked.pdf")
    with open_doc(source.path, get_password(ctx)) as doc:
        total = doc.page_count
        indices = unique(parse_pages(pages_option(ctx, "pages", "all"), total))
        ctx.progress(10)
        if kind == "text":
            _apply_text(ctx, doc, indices, overlay)
        else:
            _apply_image(ctx, doc, indices, images[0], overlay)
        ctx.progress(88)
        save_doc(doc, dest)

    return ToolResult(
        outputs=[OutputFile(dest, out_name(source.stem, "watermarked"), PDF_MIME)],
        meta={
            "pages_in": total,
            "pages_out": total,
            "input_bytes": source.path.stat().st_size,
            "output_bytes": dest.stat().st_size,
        },
    )
