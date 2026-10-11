from __future__ import annotations

import io

import pikepdf

from tests.pdf_fixtures import failure_code, numbered_pdf, result_pdf, run_tool


def _info(data: bytes) -> dict[str, str]:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return {str(key): str(value) for key, value in pdf.docinfo.items()}


def _pdf_with_xmp() -> bytes:
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page(page_size=(100, 100))
    with pdf.open_metadata() as meta:
        meta["dc:title"] = "Old XMP title"
    buffer = io.BytesIO()
    pdf.save(buffer)
    pdf.close()
    return buffer.getvalue()


def test_edit_sets_fields_and_reports_them(client):
    body, result = run_tool(
        client,
        "metadata",
        [("d.pdf", numbered_pdf(2))],
        {"title": "My Title", "author": "Jane Doe", "keywords": "a, b"},
    )
    assert body["status"] == "done", body
    info = _info(result.content)
    assert info["/Title"] == "My Title"
    assert info["/Author"] == "Jane Doe"
    assert info["/Keywords"] == "a, b"
    assert body["meta"]["metadata"]["title"] == "My Title"


def test_edit_handles_non_ascii_text(client):
    title = "R\u00e9sum\u00e9 \u2013 \u65e5\u672c\u8a9e"
    data = result_pdf(client, "metadata", [("d.pdf", numbered_pdf(1))], {"title": title})
    assert _info(data)["/Title"] == title


def test_edit_keeps_untouched_fields_and_can_clear_one(client):
    first = result_pdf(client, "metadata", [("d.pdf", numbered_pdf(1))], {"title": "T", "author": "A"})
    second = result_pdf(client, "metadata", [("d.pdf", first)], {"title": "New"})
    info = _info(second)
    assert info["/Title"] == "New"
    assert info["/Author"] == "A"
    third = result_pdf(client, "metadata", [("d.pdf", second)], {"title": ""})
    info = _info(third)
    assert "/Title" not in info
    assert info["/Author"] == "A"


def test_clear_all_removes_properties(client):
    first = result_pdf(client, "metadata", [("d.pdf", numbered_pdf(1))], {"title": "T", "author": "A"})
    data = result_pdf(client, "metadata", [("d.pdf", first)], {"clear_all": True})
    info = _info(data)
    assert "/Title" not in info
    assert "/Author" not in info


def test_read_action_reports_without_changing(client):
    first = result_pdf(client, "metadata", [("d.pdf", numbered_pdf(1))], {"title": "Hello"})
    body, result = run_tool(client, "metadata", [("d.pdf", first)], {"action": "read"})
    assert body["status"] == "done", body
    assert body["meta"]["metadata"]["title"] == "Hello"
    assert _info(result.content)["/Title"] == "Hello"


def test_editing_removes_stale_xmp(client):
    body, result = run_tool(client, "metadata", [("x.pdf", _pdf_with_xmp())], {"title": "New title"})
    assert body["status"] == "done", body
    assert body["meta"]["xmp_removed"] is True
    with pikepdf.open(io.BytesIO(result.content)) as pdf:
        assert "/Metadata" not in pdf.Root
        assert str(pdf.docinfo["/Title"]) == "New title"


def test_metadata_errors(client):
    files = [("d.pdf", numbered_pdf(1))]
    assert failure_code(client, "metadata", files, {}) == "invalid_options"
    assert failure_code(client, "metadata", files, {"title": 123}) == "invalid_options"
    assert failure_code(client, "metadata", files, {"title": "x" * 501}) == "invalid_options"
    assert failure_code(client, "metadata", files, {"action": "delete"}) == "invalid_options"
    secret = [("d.pdf", numbered_pdf(1, password="secret"))]
    assert failure_code(client, "metadata", secret, {"title": "T"}) == "password_required"
