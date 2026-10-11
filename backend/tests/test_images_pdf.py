from __future__ import annotations

import io
import zipfile

import pymupdf
import pytest

from app.tools.images_to_pdf import layout
from tests.helpers import make_pdf, post_tool
from tests.image_fixtures import image_mode, image_size, make_image
from tests.pdf_fixtures import failure_code, numbered_pdf, page_widths, result_pdf, run_tool


def _flat(result):
    page_w, page_h, (x0, y0, x1, y1) = result
    return (page_w, page_h, x0, y0, x1, y1)


def _zip_images(content: bytes) -> list[bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return [archive.read(name) for name in sorted(archive.namelist())]


# ---------------------------------------------------------------- registry

def test_stage3_tools_are_listed(client):
    names = {tool["name"] for tool in client.get("/v1/tools").json()["tools"]}
    assert {
        "images-to-pdf",
        "pdf-to-images",
        "compress",
        "protect",
        "unlock",
        "page-numbers",
        "watermark",
        "metadata",
    } <= names


# ---------------------------------------------------------------- layout maths

def test_layout_fit_keeps_small_images_and_caps_large_ones():
    assert _flat(layout(300, 200, "fit", "auto", 0)) == pytest.approx((300, 200, 0, 0, 300, 200))
    page_w, page_h, _ = layout(2000, 1000, "fit", "auto", 0)
    assert (page_w, page_h) == pytest.approx((842, 421))


def test_layout_fixed_sizes_choose_orientation_and_centre_the_image():
    assert _flat(layout(200, 100, "a4", "auto", 0)) == pytest.approx((842, 595, 0, 87, 842, 508))
    page_w, page_h, _ = layout(100, 200, "a4", "auto", 0)
    assert (page_w, page_h) == (595, 842)
    page_w, page_h, _ = layout(100, 200, "letter", "landscape", 0)
    assert (page_w, page_h) == (792, 612)


def test_layout_margin_shrinks_the_image():
    _, _, (x0, y0, x1, y1) = layout(100, 100, "a4", "portrait", 50)
    assert x1 - x0 == pytest.approx(495)
    assert y1 - y0 == pytest.approx(495)


# ---------------------------------------------------------------- images-to-pdf

def test_images_to_pdf_a4_with_auto_orientation(client):
    files = [("a.png", make_image(300, 200)), ("b.jpg", make_image(200, 300, fmt="JPEG"))]
    body, result = run_tool(client, "images-to-pdf", files)
    assert body["status"] == "done", body
    assert page_widths(result.content) == [842, 595]
    assert body["meta"]["pages_out"] == 2


def test_images_to_pdf_fit_matches_the_image(client):
    data = result_pdf(client, "images-to-pdf", [("a.png", make_image(300, 200))], {"page_size": "fit"})
    assert page_widths(data) == [300]


def test_images_to_pdf_letter_forced_landscape(client):
    data = result_pdf(
        client,
        "images-to-pdf",
        [("a.png", make_image(100, 200))],
        {"page_size": "letter", "orientation": "landscape"},
    )
    assert page_widths(data) == [792]


def test_images_to_pdf_accepts_transparent_png_and_gif(client):
    files = [
        ("a.png", make_image(100, 100, (255, 0, 0, 128), mode="RGBA")),
        ("b.gif", make_image(50, 40, (0, 128, 0), fmt="GIF")),
    ]
    data = result_pdf(client, "images-to-pdf", files)
    assert len(page_widths(data)) == 2


def test_images_to_pdf_embeds_one_image_per_page(client):
    data = result_pdf(client, "images-to-pdf", [("a.png", make_image(300, 200))])
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        assert [len(page.get_images()) for page in doc] == [1]


def test_images_to_pdf_errors(client):
    files = [("a.png", make_image(50, 50))]
    assert failure_code(client, "images-to-pdf", files, {"page_size": "b5"}) == "invalid_options"
    assert failure_code(client, "images-to-pdf", files, {"margin": 500}) == "invalid_options"
    assert failure_code(client, "images-to-pdf", files, {"quality": "ultra"}) == "invalid_options"
    broken = [("broken.png", b"\x89PNG\r\n\x1a\nthis is not really a png")]
    assert failure_code(client, "images-to-pdf", broken) == "corrupted_file"


def test_images_to_pdf_rejects_pdf_uploads(client):
    response = post_tool(client, "images-to-pdf", files=[("a.pdf", make_pdf())])
    assert response.status_code == 415


# ---------------------------------------------------------------- pdf-to-images

def test_pdf_to_images_returns_a_zip_of_jpgs(client):
    body, result = run_tool(client, "pdf-to-images", [("d.pdf", numbered_pdf(3))], {"dpi": 72})
    assert body["status"] == "done", body
    assert body["result_name"] == "d_images.zip"
    images = _zip_images(result.content)
    assert [image_size(data)[0] for data in images] == [110, 120, 130]
    assert all(data[:2] == b"\xff\xd8" for data in images)
    assert body["meta"]["pages_out"] == 3


def test_pdf_to_images_single_page_is_a_plain_image(client):
    body, result = run_tool(client, "pdf-to-images", [("d.pdf", numbered_pdf(3))], {"pages": "2", "dpi": 72})
    assert body["status"] == "done", body
    assert result.content[:2] == b"\xff\xd8"
    assert image_size(result.content) == (120, 200)


def test_pdf_to_images_png_and_dpi(client):
    data = result_pdf(
        client, "pdf-to-images", [("d.pdf", numbered_pdf(1))], {"format": "png", "dpi": 144}
    )
    assert data[:4] == b"\x89PNG"
    assert image_size(data) == (220, 400)


def test_pdf_to_images_grayscale(client):
    data = result_pdf(
        client, "pdf-to-images", [("d.pdf", numbered_pdf(1))], {"grayscale": True, "dpi": 72}
    )
    assert image_mode(data) == "L"


def test_pdf_to_images_password_flow(client):
    files = [("d.pdf", numbered_pdf(2, password="secret"))]
    assert failure_code(client, "pdf-to-images", files) == "password_required"
    assert failure_code(client, "pdf-to-images", files, {"password": "nope"}) == "wrong_password"
    data = result_pdf(client, "pdf-to-images", files, {"password": "secret", "pages": "1", "dpi": 72})
    assert image_size(data) == (110, 200)


def test_pdf_to_images_errors(client):
    files = [("d.pdf", numbered_pdf(2))]
    assert failure_code(client, "pdf-to-images", files, {"dpi": 50}) == "invalid_options"
    assert failure_code(client, "pdf-to-images", files, {"format": "gif"}) == "invalid_options"
    assert failure_code(client, "pdf-to-images", files, {"pages": "9"}) == "invalid_options"
