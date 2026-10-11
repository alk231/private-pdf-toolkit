"""Page-range parsing shared by the page tools. Light: no PDF libraries."""
from __future__ import annotations

import re

from app.tools.base import ToolError

MAX_SELECTION = 10_000
HELP = "Use page numbers like 1-3,5,8-"

_DIGITS = re.compile(r"[0-9]+")


def _bad(message: str) -> ToolError:
    return ToolError("invalid_options", message)


def _number(text: str, total: int) -> int:
    word = text.strip().lower()
    if word in ("last", "end"):
        return total
    if not _DIGITS.fullmatch(word):
        raise _bad(f"'{word[:20]}' is not a valid page number. {HELP}.")
    if len(word) > 9:
        return total + 1  # certainly out of range; the caller reports it
    return int(word)


def parse_groups(spec: str, total: int, *, allow_reverse: bool = True) -> list[list[int]]:
    """Parse '1-3,5,7-' into one group of 0-based page indices per comma-separated token."""
    if not isinstance(spec, str):
        raise _bad(f"Enter the pages you want. {HELP}.")
    text = spec.strip().lower().replace("\u2013", "-").replace("\u2014", "-").replace(";", ",")
    if not text:
        raise _bad(f"Enter the pages you want. {HELP}.")
    if text == "all":
        return [list(range(total))]

    groups: list[list[int]] = []
    count = 0
    for raw in text.split(","):
        token = raw.strip()
        if not token:
            continue
        if "-" in token:
            left, _, right = token.partition("-")
            if "-" in right:
                raise _bad(f"'{token[:20]}' is not a valid range. {HELP}.")
            start = _number(left, total) if left.strip() else 1
            end = _number(right, total) if right.strip() else total
        else:
            start = end = _number(token, total)

        for page in (start, end):
            if page < 1 or page > total:
                plural = "" if total == 1 else "s"
                raise _bad(f"Page {page} does not exist; this PDF has {total} page{plural}.")

        if start <= end:
            group = list(range(start - 1, end))
        elif allow_reverse:
            group = list(range(start - 1, end - 2, -1))
        else:
            raise _bad("Ranges must go from a lower to a higher page, like 2-5.")

        count += len(group)
        if count > MAX_SELECTION:
            raise _bad("That page selection is too long.")
        groups.append(group)

    if not groups:
        raise _bad(f"Enter the pages you want. {HELP}.")
    return groups


def parse_pages(spec: str, total: int, *, allow_reverse: bool = True) -> list[int]:
    """Flat list of 0-based page indices, in the order written (duplicates kept)."""
    return [index for group in parse_groups(spec, total, allow_reverse=allow_reverse) for index in group]


def unique(items: list[int]) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
