from __future__ import annotations

import io

import pikepdf
import pymupdf
import pytest

from tests.image_fixtures import make_image
from tests.pdf_fixtures import failure_code, numbered_pdf, page_rotations, result_pdf, run_tool


def _texts(data: bytes) -> list[str]:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return [page.get_text().strip() for page in doc]


def _words(data: bytes, index: int = 0):
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return doc[index].get_text("words")


def _opacities(data: bytes) -> list[float]:
    values: list[float] = []
    with pikepdf.open(io.BytesIO(data)) as pdf:
        resources = pdf.pages[0].obj.get("/Resources")
        states = resources.get("/ExtGState") if resources is not None else None
        if states is not None:
            for key in states.keys():
                if "/ca" in states[key]:
                    values.append(float(states[key]["/ca"]))
    return values


# ---------------------------------------------------------------- page numbers

def test_page_numbers_default_bottom_centre(client):
    data = result_pdf(client, "page-numbers", [("d.pdf", numbered_pdf(3))])
    assert _texts(data) == ["1", "2", "3"]
    x0, y0, x1, y1, word = _words(data)[0][:5]
    assert word == "1"
    assert y0 > 150
    assert abs((x0 + x1) / 2 - 55) < 8


def test_page_numbers_format_start_and_page_selection(client):
    data = result_pdf(
        client,
        "page-numbers",
        [("d.pdf", numbered_pdf(3))],
        {"format": "page_n_of_total", "start": 5, "pages": "2-"},
    )
    assert _texts(data) == ["", "Page 5 of 6", "Page 6 of 6"]


def test_page_numbers_top_left(client):
    data = result_pdf(
        client, "page-numbers", [("d.pdf", numbered_pdf(1))], {"position": "top-left", "margin": 20}
    )
    x0, y0, x1, y1, _ = _words(data)[0][:5]
    assert y1 < 50
    assert 15 < x0 < 28


def test_page_numbers_on_a_rotated_page(client):
    rotated = result_pdf(client, "rotate", [("d.pdf", numbered_pdf(1))], {"angle": 90})
    data = result_pdf(client, "page-numbers", [("d.pdf", rotated)])
    assert _texts(data) == ["1"]
    assert page_rotations(data) == [90]


def test_page_numbers_password_and_option_errors(client):
    files = [("d.pdf", numbered_pdf(2, password="secret"))]
    assert failure_code(client, "page-numbers", files) == "password_required"
    data = result_pdf(client, "page-numbers", files, {"password": "secret"})
    assert _texts(data) == ["1", "2"]
    plain = [("d.pdf", numbered_pdf(2))]
    assert failure_code(client, "page-numbers", plain, {"position": "middle"}) == "invalid_options"
    assert failure_code(client, "page-numbers", plain, {"format": "roman"}) == "invalid_options"
    assert failure_code(client, "page-numbers", plain, {"color": "red"}) == "invalid_options"
    assert failure_code(client, "page-numbers", plain, {"font_size": 2}) == "invalid_options"
    assert failure_code(client, "page-numbers", plain, {"pages": "9"}) == "invalid_options"


# ---------------------------------------------------------------- text watermark

def test_text_watermark_is_added_to_every_page(client):
    data = result_pdf(
        client, "watermark", [("d.pdf", numbered_pdf(2))], {"text": "DRAFT", "angle": 0}
    )
    texts = ["".join(text.split()) for text in _texts(data)]
    assert all("DRAFT" in text for text in texts)


def test_text_watermark_only_on_selected_pages(client):
    data = result_pdf(
        client,
        "watermark",
        [("d.pdf", numbered_pdf(3))],
        {"text": "DRAFT", "angle": 0, "pages": "2"},
    )
    texts = ["".join(text.split()) for text in _texts(data)]
    assert [("DRAFT" in text) for text in texts] == [False, True, False]


def test_text_watermark_is_diagonal_by_default(client):
    data = result_pdf(client, "watermark", [("d.pdf", numbered_pdf(1))], {"text": "DRAFT"})
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        lines = [
            line
            for block in doc[0].get_text("dict")["blocks"]
            for line in block.get("lines", [])
        ]
    assert lines
    dx, dy = lines[0]["dir"]
    assert abs(dx) > 0.5 and abs(dy) > 0.5


def test_text_watermark_shrinks_to_fit_the_page(client):
    data = result_pdf(
        client,
        "watermark",
        [("d.pdf", numbered_pdf(1))],
        {"text": "CONFIDENTIAL", "angle": 0, "font_size": 300},
    )
    x0, _, x1, _, _ = _words(data)[0][:5]
    assert x0 >= 0
    assert x1 <= 110


def test_text_watermark_opacity_is_applied(client):
    data = result_pdf(
        client, "watermark", [("d.pdf", numbered_pdf(1))], {"text": "DRAFT", "opacity": 0.3}
    )
    assert any(abs(value - 0.3) < 0.01 for value in _opacities(data))


def test_text_watermark_on_rotated_page_and_under_layer(client):
    rotated = result_pdf(client, "rotate", [("d.pdf", numbered_pdf(1))], {"angle": 90})
    data = result_pdf(client, "watermark", [("d.pdf", rotated)], {"text": "DRAFT"})
    assert page_rotations(data) == [90]
    data = result_pdf(
        client, "watermark", [("d.pdf", numbered_pdf(1))], {"text": "DRAFT", "angle": 0, "layer": "under"}
    )
    assert "DRAFT" in "".join(_texts(data)[0].split())


def test_text_watermark_option_errors(client):
    files = [("d.pdf", numbered_pdf(1))]
    assert failure_code(client, "watermark", files, {}) == "invalid_options"
    assert failure_code(client, "watermark", files, {"text": "   "}) == "invalid_options"
    assert failure_code(client, "watermark", files, {"text": "\u0928\u092e\u0938\u094d\u0924\u0947"}) == "invalid_options"
    assert failure_code(client, "watermark", files, {"text": "X", "opacity": 0}) == "invalid_options"
    assert failure_code(client, "watermark", files, {"text": "X", "color": "red"}) == "invalid_options"
    assert failure_code(client, "watermark", files, {"text": "X", "type": "stamp"}) == "invalid_options"
    assert failure_code(client, "watermark", files, {"text": "X", "layer": "middle"}) == "invalid_options"


# ---------------------------------------------------------------- image watermark

def test_image_watermark_is_added_to_every_page(client):
    logo = make_image(80, 40, (0, 0, 255, 255), mode="RGBA")
    data = result_pdf(
        client,
        "watermark",
        [("d.pdf", numbered_pdf(2)), ("logo.png", logo)],
        {"type": "image", "scale": 40},
    )
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        assert [len(page.get_images()) for page in doc] == [1, 1]


def test_image_watermark_accepts_either_upload_order_and_rotation(client):
    logo = make_image(80, 40, (0, 0, 255, 255), mode="RGBA")
    rotated = result_pdf(client, "rotate", [("d.pdf", numbered_pdf(1))], {"angle": 90})
    data = result_pdf(
        client,
        "watermark",
        [("logo.png", logo), ("d.pdf", rotated)],
        {"type": "image", "angle": 30, "opacity": 0.6},
    )
    assert page_rotations(data) == [90]
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        assert len(doc[0].get_images()) == 1


def test_watermark_file_errors(client):
    pdf = ("d.pdf", numbered_pdf(1))
    logo = ("logo.png", make_image(20, 20))
    assert failure_code(client, "watermark", [pdf], {"type": "image"}) == "invalid_files"
    assert failure_code(client, "watermark", [pdf, logo], {"text": "X"}) == "invalid_files"
    assert failure_code(client, "watermark", [logo], {"text": "X"}) == "invalid_files"
    broken = ("logo.png", b"\x89PNG\r\n\x1a\nnot really a png")
    assert failure_code(client, "watermark", [pdf, broken], {"type": "image"}) == "corrupted_file"
