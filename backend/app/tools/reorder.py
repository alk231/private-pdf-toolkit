"""Reorder pages. Also used by the page organizer: drop_missing deletes unlisted pages, rotations turns pages."""
from __future__ import annotations

import re
from typing import Any

from app.tools.base import ToolContext, ToolError, ToolResult
from app.tools.pagespec import parse_pages
from app.tools.pdfutil import copy_pages, get_password, open_pdf, pages_option, save_pdf, single_result

_KEY = re.compile(r"[0-9]{1,9}")


def _rotations(raw: Any, total: int) -> dict[int, int]:
    """{"3": 90} -> {2: 90}: degrees clockwise to add, keyed by ORIGINAL page number."""
    if raw is None:
        return {}
    if not isinstance(raw, dict) or len(raw) > total:
        raise ToolError("invalid_options", "The option 'rotations' must map page numbers to degrees.")
    result: dict[int, int] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ToolError("invalid_options", "The option 'rotations' has an invalid page number.")
        page = int(key)
        if page < 1 or page > total:
            raise ToolError("invalid_options", f"Rotation page {page} does not exist.")
        if isinstance(value, bool) or not isinstance(value, int) or value % 90 != 0:
            raise ToolError("invalid_options", "Rotations must be multiples of 90 degrees.")
        if value % 360:
            result[page - 1] = value % 360
    return result


def run(ctx: ToolContext) -> ToolResult:
    item = ctx.inputs[0]
    dest = ctx.out_path("reordered.pdf")
    drop_missing = ctx.opt_bool("drop_missing", False)

    with open_pdf(item.path, get_password(ctx)) as source:
        total = len(source.pages)
        requested = parse_pages(pages_option(ctx, "order"), total)
        if len(set(requested)) != len(requested):
            raise ToolError("invalid_options", "Each page can appear only once in the new order.")

        order = list(requested)
        if not drop_missing:
            listed = set(requested)
            order.extend(index for index in range(total) if index not in listed)

        rotations = _rotations(ctx.options.get("rotations"), total)
        ctx.progress(20)
        with copy_pages(source, order) as result:
            for position, original in enumerate(order):
                angle = rotations.get(original)
                if angle:
                    result.pages[position].rotate(angle, True)
            ctx.progress(70)
            save_pdf(result, dest)

    return single_result(ctx, dest, "reordered", total, len(order))
