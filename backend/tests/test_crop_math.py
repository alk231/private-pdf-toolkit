from __future__ import annotations

import pytest

from app.tools.base import ToolError
from app.tools.crop import crop_rect

BOX = (0.0, 0.0, 200.0, 100.0)
MARGINS = (10.0, 20.0, 30.0, 5.0)  # left, top, right, bottom as seen on screen


@pytest.mark.parametrize(
    "rotation, expected",
    [
        (0, (10, 5, 170, 80)),
        (90, (20, 10, 195, 70)),
        (180, (30, 20, 190, 95)),
        (270, (5, 30, 180, 90)),
        (-90, (5, 30, 180, 90)),
        (45, (10, 5, 170, 80)),  # unsupported rotation is treated as 0
    ],
)
def test_points_follow_page_rotation(rotation, expected):
    assert crop_rect(BOX, rotation, MARGINS, "points") == pytest.approx(expected)


def test_percent_uses_visible_size():
    assert crop_rect(BOX, 0, (10, 0, 0, 0), "percent") == pytest.approx((20, 0, 200, 100))
    # rotated 90: the visible width is the page height (100), so 10% = 10 points
    assert crop_rect(BOX, 90, (10, 0, 0, 0), "percent") == pytest.approx((0, 10, 200, 100))


def test_offset_box_is_respected():
    assert crop_rect((50, 60, 250, 160), 0, (10, 10, 10, 10), "points") == pytest.approx((60, 70, 240, 150))


@pytest.mark.parametrize(
    "margins, unit",
    [((100, 0, 95, 0), "points"), ((60, 0, 60, 0), "percent"), ((0, 60, 0, 60), "percent")],
)
def test_too_small_area_is_rejected(margins, unit):
    with pytest.raises(ToolError) as info:
        crop_rect(BOX, 0, margins, unit)
    assert info.value.code == "invalid_options"
