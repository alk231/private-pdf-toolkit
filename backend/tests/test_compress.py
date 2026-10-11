from __future__ import annotations

import io
import os
import shutil

import pikepdf
import pymupdf
import pytest
from PIL import Image

from tests.pdf_fixtures import failure_code, numbered_pdf, result_pdf, run_tool

requires_gs = pytest.mark.skipif(
    shutil.which("gs") is None,
    reason="Ghostscript is not installed here; run these tests inside the Docker image (see Stage 3 notes)",
)


def _noisy_pdf() -> bytes:
    """A PDF with a large, incompressible lossless image: Ghostscript can shrink this a lot."""
    side = 1400
    noise = Image.frombytes("RGB", (side, side), os.urandom(side * side * 3))
    buffer = io.BytesIO()
    noise.save(buffer, "PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=600)
    page.insert_image(page.rect, stream=buffer.getvalue())
    data = doc.tobytes(deflate=True)
    doc.close()
    return data


@requires_gs
def test_compress_shrinks_and_reports_sizes(client):
    original = _noisy_pdf()
    body, result = run_tool(client, "compress", [("big.pdf", original)], {"level": "screen"})
    assert body["status"] == "done", body
    meta = body["meta"]
    assert meta["input_bytes"] == len(original)
    assert meta["output_bytes"] == len(result.content)
    assert meta["output_bytes"] < meta["input_bytes"] / 2
    assert meta["already_optimized"] is False
    assert meta["saved_percent"] > 50
    with pikepdf.open(io.BytesIO(result.content)) as pdf:
        assert len(pdf.pages) == 1


@requires_gs
def test_compress_never_returns_a_bigger_file(client):
    small = numbered_pdf(3)
    body, result = run_tool(client, "compress", [("d.pdf", small)])
    assert body["status"] == "done", body
    assert len(result.content) <= len(small)
    assert body["meta"]["output_bytes"] <= body["meta"]["input_bytes"]
    with pikepdf.open(io.BytesIO(result.content)) as pdf:
        assert len(pdf.pages) == 3


@requires_gs
def test_compress_decrypts_with_the_password(client):
    files = [("d.pdf", numbered_pdf(2, password="secret"))]
    data = result_pdf(client, "compress", files, {"password": "secret"})
    with pikepdf.open(io.BytesIO(data)) as pdf:
        assert len(pdf.pages) == 2


def test_compress_password_errors(client):
    files = [("d.pdf", numbered_pdf(2, password="secret"))]
    assert failure_code(client, "compress", files) == "password_required"
    assert failure_code(client, "compress", files, {"password": "nope"}) == "wrong_password"


def test_compress_validates_options_and_input(client):
    assert failure_code(client, "compress", [("d.pdf", numbered_pdf(1))], {"level": "extreme"}) == "invalid_options"
    broken = [("broken.pdf", b"%PDF-1.4\nthis is not a real pdf at all\n")]
    assert failure_code(client, "compress", broken) == "corrupted_file"
