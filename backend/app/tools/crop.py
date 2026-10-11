"""Crop pages by trimming margins (percent of the visible page, or points).

Margins are measured on the page as it appears on screen (after /Rotate).
Cropping hides the trimmed area; it does not delete the content underneath.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import pikepdf

from app.tools.base import ToolContext, ToolError, ToolResult
from app.tools.pagespec import parse_pages, unique
from app.tools.pdfutil import get_password, open_pdf, opt_float, pages_option, save_pdf, single_result

MIN_SIDE_PT = 10.0
_DEFAULT_BOX = (0.0, 0.0, 612.0, 792.0)


def crop_rect(
    box: tuple[float, float, float, float],
    rotation: int,
    margins: tuple[float, float, float, float],
    unit: str,
) -> tuple[float, float, float, float]:
    """New (x0, y0, x1, y1) in unrotated page space. margins = (left, top, right, bottom) as seen on screen."""
    x0, y0, x1, y1 = box
    width = x1 - x0
    height = y1 - y0
    rot = rotation % 360
    if rot % 90 != 0:
        rot = 0
    visible_w, visible_h = (height, width) if rot in (90, 270) else (width, height)

    left, top, right, bottom = margins
    if unit == "percent":
        left, right = visible_w * left / 100.0, visible_w * right / 100.0
        top, bottom = visible_h * top / 100.0, visible_h * bottom / 100.0

    if visible_w - left - right < MIN_SIDE_PT or visible_h - top - bottom < MIN_SIDE_PT:
        raise ToolError("invalid_options", "The crop area is too small. Use smaller margins.")

    if rot == 0:
        return (x0 + left, y0 + bottom, x1 - right, y1 - top)
    if rot == 90:
        return (x0 + top, y0 + left, x1 - bottom, y1 - right)
    if rot == 180:
        return (x0 + right, y0 + top, x1 - left, y1 - bottom)
    return (x0 + bottom, y0 + right, x1 - top, y1 - left)


def _inherited(obj: Any, key: str) -> Any:
    node = obj
    for _ in range(64):
        if key in node:
            return node[key]
        parent = node.get("/Parent")
        if parent is None:
            return None
        node = parent
    return None


def _box(obj: Any, key: str) -> tuple[float, float, float, float] | None:
    value = _inherited(obj, key)
    if value is None:
        return None
    try:
        numbers = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    if len(numbers) != 4:
        return None
    a, b, c, d = numbers
    return (min(a, c), min(b, d), max(a, c), max(b, d))


def _effective_box(obj: Any) -> tuple[float, float, float, float]:
    media = _box(obj, "/MediaBox") or _DEFAULT_BOX
    crop = _box(obj, "/CropBox")
    if crop is None:
        return media
    x0, y0 = max(media[0], crop[0]), max(media[1], crop[1])
    x1, y1 = min(media[2], crop[2]), min(media[3], crop[3])
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return media
    return (x0, y0, x1, y1)


def _rotation(obj: Any) -> int:
    value = _inherited(obj, "/Rotate")
    try:
        return int(value) % 360 if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _array(rect: tuple[float, float, float, float]) -> pikepdf.Array:
    return pikepdf.Array([Decimal(f"{v:.2f}") for v in rect])


def run(ctx: ToolContext) -> ToolResult:
    item = ctx.inputs[0]
    dest = ctx.out_path("cropped.pdf")

    unit = ctx.opt_str("unit", "percent", allowed=("percent", "points"))
    limit = 95.0 if unit == "percent" else 5000.0
    margins = tuple(
        opt_float(ctx, key, 0.0, minimum=0.0, maximum=limit)
        for key in ("left", "top", "right", "bottom")
    )
    if not any(margins):
        raise ToolError("invalid_options", "Set at least one margin to crop.")

    with open_pdf(item.path, get_password(ctx)) as pdf:
        total = len(pdf.pages)
        indices = unique(parse_pages(pages_option(ctx, "pages", "all"), total))
        ctx.progress(20)
        for count, index in enumerate(indices, start=1):
            page_obj = pdf.pages[index].obj
            rect = crop_rect(_effective_box(page_obj), _rotation(page_obj), margins, unit)  # type: ignore[arg-type]
            page_obj["/CropBox"] = _array(rect)
            page_obj["/MediaBox"] = _array(rect)
            for extra in ("/TrimBox", "/BleedBox", "/ArtBox"):
                if extra in page_obj:
                    del page_obj[extra]
            if count % 25 == 0:
                ctx.progress(20 + 50 * count // len(indices))
        ctx.progress(75)
        save_pdf(pdf, dest)

    return single_result(ctx, dest, "cropped", total, total)
