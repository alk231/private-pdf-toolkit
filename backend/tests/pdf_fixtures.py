"""Generated PDFs and readers for the page-tool tests.

Page n of numbered_pdf() is (100 + 10*n) points wide, so every page is recognisable by its width.
"""
from __future__ import annotations

import io
from typing import Any

import pikepdf

from tests.helpers import post_tool, wait_for_status


def width_of(page_number: int) -> int:
    return 100 + 10 * page_number


def widths_for(*page_numbers: int) -> list[int]:
    return [width_of(n) for n in page_numbers]


def numbered_pdf(pages: int, *, password: str | None = None) -> bytes:
    pdf = pikepdf.Pdf.new()
    try:
        for number in range(1, pages + 1):
            pdf.add_blank_page(page_size=(width_of(number), 200))
        buffer = io.BytesIO()
        if password:
            pdf.save(buffer, encryption=pikepdf.Encryption(owner=password, user=password))
        else:
            pdf.save(buffer)
        return buffer.getvalue()
    finally:
        pdf.close()


def page_widths(data: bytes) -> list[int]:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        result = []
        for page in pdf.pages:
            box = page.obj["/MediaBox"]
            result.append(round(float(box[2]) - float(box[0])))
        return result


def page_rotations(data: bytes) -> list[int]:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return [int(page.obj.get("/Rotate", 0)) for page in pdf.pages]


def page_box(data: bytes, index: int, key: str) -> tuple[float, ...] | None:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        value = pdf.pages[index].obj.get(key)
        if value is None:
            return None
        return tuple(float(v) for v in value)


def run_tool(
    client: Any,
    tool: str,
    files: list[tuple[str, bytes]],
    options: dict[str, Any] | None = None,
):
    """Submit a job, wait for it, and download the result if it succeeded."""
    created = post_tool(client, tool, files=files, options=options)
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    body = wait_for_status(client, job_id)
    if body["status"] != "done":
        return body, None
    result = client.get(f"/v1/jobs/{job_id}/result")
    assert result.status_code == 200, result.text
    return body, result


def result_pdf(client: Any, tool: str, files: list[tuple[str, bytes]], options: dict[str, Any] | None = None) -> bytes:
    body, result = run_tool(client, tool, files, options)
    assert body["status"] == "done", body
    return result.content


def failure_code(client: Any, tool: str, files: list[tuple[str, bytes]], options: dict[str, Any] | None = None) -> str:
    body, _ = run_tool(client, tool, files, options)
    assert body["status"] == "failed", body
    return body["error"]["code"]
