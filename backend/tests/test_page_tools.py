from __future__ import annotations

import io
import zipfile
from urllib.parse import unquote

import pytest

from tests.helpers import post_tool
from tests.pdf_fixtures import (
    failure_code,
    numbered_pdf,
    page_box,
    page_rotations,
    page_widths,
    result_pdf,
    run_tool,
    widths_for as w,
)


def _zip_page_widths(content: bytes) -> list[list[int]]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return [page_widths(archive.read(name)) for name in sorted(archive.namelist())]


# ---------------------------------------------------------------- registry

def test_tools_are_listed(client):
    names = {tool["name"] for tool in client.get("/v1/tools").json()["tools"]}
    assert {"merge", "split", "extract-pages", "remove-pages", "reorder", "rotate", "crop"} <= names


# ---------------------------------------------------------------- merge

def test_merge_keeps_upload_order(client):
    body, result = run_tool(client, "merge", [("a.pdf", numbered_pdf(2)), ("b.pdf", numbered_pdf(3))])
    assert body["status"] == "done", body
    assert page_widths(result.content) == w(1, 2, 1, 2, 3)
    assert body["meta"]["pages_out"] == 5
    assert "merged.pdf" in unquote(result.headers["content-disposition"])


def test_merge_needs_two_files(client):
    response = post_tool(client, "merge", files=[("a.pdf", numbered_pdf(1))])
    assert response.status_code == 400


def test_merge_encrypted_file_needs_password(client):
    files = [("a.pdf", numbered_pdf(2, password="secret")), ("b.pdf", numbered_pdf(1))]
    assert failure_code(client, "merge", files) == "password_required"
    assert failure_code(client, "merge", files, {"passwords": ["nope", None]}) == "wrong_password"
    data = result_pdf(client, "merge", files, {"passwords": ["secret", None]})
    assert page_widths(data) == w(1, 2, 1)


def test_merge_rejects_bad_passwords_option(client):
    files = [("a.pdf", numbered_pdf(1)), ("b.pdf", numbered_pdf(1))]
    assert failure_code(client, "merge", files, {"passwords": "secret"}) == "invalid_options"


# ---------------------------------------------------------------- split

def test_split_by_ranges_returns_zip(client):
    body, result = run_tool(client, "split", [("doc.pdf", numbered_pdf(5))], {"mode": "ranges", "ranges": "1-2,4"})
    assert body["status"] == "done", body
    assert body["result_name"] == "doc_split.zip"
    assert _zip_page_widths(result.content) == [w(1, 2), w(4)]
    assert body["meta"]["parts"] == 2


def test_split_every_n_pages(client):
    body, result = run_tool(client, "split", [("doc.pdf", numbered_pdf(5))], {"mode": "every", "every": 2})
    assert body["status"] == "done", body
    assert _zip_page_widths(result.content) == [w(1, 2), w(3, 4), w(5)]


def test_split_single_range_returns_plain_pdf(client):
    body, result = run_tool(client, "split", [("doc.pdf", numbered_pdf(5))], {"ranges": "2-3"})
    assert body["status"] == "done", body
    assert result.content[:4] == b"%PDF"
    assert page_widths(result.content) == w(2, 3)


def test_split_every_larger_than_document_is_rejected(client):
    assert failure_code(client, "split", [("d.pdf", numbered_pdf(5))], {"mode": "every", "every": 10}) == "invalid_options"


def test_split_validates_mode_and_reverse_ranges(client):
    files = [("d.pdf", numbered_pdf(5))]
    assert failure_code(client, "split", files, {"mode": "weird"}) == "invalid_options"
    assert failure_code(client, "split", files, {"ranges": "4-2"}) == "invalid_options"
    assert failure_code(client, "split", files, {"ranges": "9"}) == "invalid_options"


# ---------------------------------------------------------------- extract / remove

def test_extract_pages(client):
    files = [("d.pdf", numbered_pdf(5))]
    assert page_widths(result_pdf(client, "extract-pages", files, {"pages": "2,4-5"})) == w(2, 4, 5)
    assert page_widths(result_pdf(client, "extract-pages", files, {"pages": "3-1"})) == w(3, 2, 1)
    assert page_widths(result_pdf(client, "extract-pages", files, {"pages": [5, 1]})) == w(5, 1)
    assert page_widths(result_pdf(client, "extract-pages", files, {"pages": "1,1,2"})) == w(1, 2)


def test_extract_pages_errors(client):
    files = [("d.pdf", numbered_pdf(5))]
    assert failure_code(client, "extract-pages", files, {"pages": "9"}) == "invalid_options"
    assert failure_code(client, "extract-pages", files, {}) == "invalid_options"


def test_remove_pages(client):
    files = [("d.pdf", numbered_pdf(5))]
    assert page_widths(result_pdf(client, "remove-pages", files, {"pages": "2,4"})) == w(1, 3, 5)
    assert failure_code(client, "remove-pages", files, {"pages": "all"}) == "invalid_options"


# ---------------------------------------------------------------- reorder

def test_reorder_full_order(client):
    files = [("d.pdf", numbered_pdf(3))]
    assert page_widths(result_pdf(client, "reorder", files, {"order": "3,1,2"})) == w(3, 1, 2)


def test_reorder_appends_missing_pages_unless_dropping(client):
    files = [("d.pdf", numbered_pdf(3))]
    assert page_widths(result_pdf(client, "reorder", files, {"order": [3, 1]})) == w(3, 1, 2)
    assert page_widths(result_pdf(client, "reorder", files, {"order": [3, 1], "drop_missing": True})) == w(3, 1)


def test_reorder_with_rotations_for_the_organizer(client):
    files = [("d.pdf", numbered_pdf(3))]
    data = result_pdf(
        client, "reorder", files, {"order": [3, 1, 2], "rotations": {"1": 90, "2": -90}}
    )
    assert page_widths(data) == w(3, 1, 2)
    assert page_rotations(data) == [0, 90, 270]


def test_reorder_errors(client):
    files = [("d.pdf", numbered_pdf(3))]
    assert failure_code(client, "reorder", files, {"order": [1, 1]}) == "invalid_options"
    assert failure_code(client, "reorder", files, {"order": [1], "rotations": {"1": 45}}) == "invalid_options"
    assert failure_code(client, "reorder", files, {"order": [1], "rotations": {"9": 90}}) == "invalid_options"
    assert failure_code(client, "reorder", files, {}) == "invalid_options"


# ---------------------------------------------------------------- rotate

def test_rotate_all_pages_by_default(client):
    data = result_pdf(client, "rotate", [("d.pdf", numbered_pdf(3))])
    assert page_rotations(data) == [90, 90, 90]
    assert page_widths(data) == w(1, 2, 3)


def test_rotate_selected_pages_and_negative_angle(client):
    files = [("d.pdf", numbered_pdf(3))]
    assert page_rotations(result_pdf(client, "rotate", files, {"angle": 180, "pages": "2"})) == [0, 180, 0]
    assert page_rotations(result_pdf(client, "rotate", [("d.pdf", numbered_pdf(2))], {"angle": -90})) == [270, 270]


def test_rotate_accumulates(client):
    once = result_pdf(client, "rotate", [("d.pdf", numbered_pdf(2))])
    twice = result_pdf(client, "rotate", [("d.pdf", once)])
    assert page_rotations(twice) == [180, 180]


def test_rotate_errors(client):
    files = [("d.pdf", numbered_pdf(2))]
    assert failure_code(client, "rotate", files, {"angle": 45}) == "invalid_options"
    assert failure_code(client, "rotate", files, {"angle": 0}) == "invalid_options"
    assert failure_code(client, "rotate", files, {"pages": "9"}) == "invalid_options"


# ---------------------------------------------------------------- crop

def test_crop_percent(client):
    data = result_pdf(client, "crop", [("d.pdf", numbered_pdf(2))], {"left": 10, "right": 10})
    assert page_box(data, 0, "/CropBox") == pytest.approx((11, 0, 99, 200))
    assert page_box(data, 0, "/MediaBox") == pytest.approx((11, 0, 99, 200))
    assert page_box(data, 1, "/CropBox") == pytest.approx((12, 0, 108, 200))


def test_crop_points_on_selected_page_only(client):
    data = result_pdf(client, "crop", [("d.pdf", numbered_pdf(2))], {"left": 20, "unit": "points", "pages": "1"})
    assert page_box(data, 0, "/CropBox") == pytest.approx((20, 0, 110, 200))
    assert page_box(data, 1, "/CropBox") is None


def test_crop_respects_page_rotation(client):
    rotated = result_pdf(client, "rotate", [("d.pdf", numbered_pdf(1))], {"angle": 90})
    data = result_pdf(client, "crop", [("d.pdf", rotated)], {"top": 10, "unit": "points"})
    assert page_box(data, 0, "/CropBox") == pytest.approx((10, 0, 110, 200))


def test_crop_errors(client):
    files = [("d.pdf", numbered_pdf(1))]
    assert failure_code(client, "crop", files, {}) == "invalid_options"
    assert failure_code(client, "crop", files, {"left": 60, "right": 60}) == "invalid_options"
    assert failure_code(client, "crop", files, {"left": 99}) == "invalid_options"
    assert failure_code(client, "crop", files, {"left": "abc"}) == "invalid_options"
    assert failure_code(client, "crop", files, {"left": 5, "unit": "inches"}) == "invalid_options"


# ---------------------------------------------------------------- passwords and bad files

def test_single_file_tools_accept_a_password(client):
    files = [("d.pdf", numbered_pdf(3, password="secret"))]
    assert failure_code(client, "extract-pages", files, {"pages": "1"}) == "password_required"
    assert failure_code(client, "extract-pages", files, {"pages": "1", "password": "nope"}) == "wrong_password"
    data = result_pdf(client, "extract-pages", files, {"pages": "2-3", "password": "secret"})
    assert page_widths(data) == w(2, 3)


def test_corrupted_pdf_is_reported(client):
    files = [("broken.pdf", b"%PDF-1.4\nthis is not a real pdf at all\n")]
    assert failure_code(client, "rotate", files) == "corrupted_file"
