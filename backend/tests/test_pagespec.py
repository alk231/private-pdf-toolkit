from __future__ import annotations

import pytest

from app.tools.base import ToolError
from app.tools.pagespec import parse_groups, parse_pages, unique


def test_basic_ranges_and_singles():
    assert parse_pages("1-3,5", 6) == [0, 1, 2, 4]


def test_all_open_ended_and_last():
    assert parse_pages("all", 3) == [0, 1, 2]
    assert parse_pages("ALL", 3) == [0, 1, 2]
    assert parse_pages("4-", 6) == [3, 4, 5]
    assert parse_pages("-2", 6) == [0, 1]
    assert parse_pages("last", 6) == [5]
    assert parse_pages("2-last", 4) == [1, 2, 3]


def test_whitespace_semicolons_and_empty_tokens():
    assert parse_pages(" 1 - 2 ; 4 ,, 6 ", 6) == [0, 1, 3, 5]


def test_reverse_ranges():
    assert parse_pages("3-1", 6) == [2, 1, 0]
    with pytest.raises(ToolError) as info:
        parse_pages("3-1", 6, allow_reverse=False)
    assert info.value.code == "invalid_options"


@pytest.mark.parametrize("spec", ["", "   ", "7", "0", "a", "1-2-3", "1-x", ",", "99999999999999"])
def test_invalid_specs(spec):
    with pytest.raises(ToolError) as info:
        parse_pages(spec, 6)
    assert info.value.code == "invalid_options"


def test_non_text_spec_is_rejected():
    with pytest.raises(ToolError):
        parse_pages(None, 6)  # type: ignore[arg-type]


def test_groups_keep_one_group_per_token():
    assert parse_groups("1-2,4,6-", 6) == [[0, 1], [3], [5]]


def test_selection_size_is_capped():
    with pytest.raises(ToolError):
        parse_pages("1-9999,1-9999", 9999)


def test_unique_keeps_first_occurrence():
    assert unique([2, 0, 2, 1, 0]) == [2, 0, 1]
