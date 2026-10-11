"""Small helpers shared by the tests (no PDF libraries needed)."""
from __future__ import annotations

import json
import time
from typing import Any


def make_pdf(pages: int = 1) -> bytes:
    """Build a tiny valid PDF with blank pages."""
    kids = " ".join(f"{3 + i} 0 R" for i in range(pages))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode("ascii"),
    ] + [b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>" for _ in range(pages)]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


def padded_pdf(total_bytes: int) -> bytes:
    """A PDF-looking file of roughly the requested size (for size-limit tests)."""
    pdf = make_pdf(1)
    return pdf + b"\n%" + b"0" * max(0, total_bytes - len(pdf) - 2)


def post_tool(
    client: Any,
    tool: str,
    files: list[tuple[str, bytes]] | None = None,
    options: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
):
    if files is None:
        files = [("a.pdf", make_pdf())]
    multipart = [("files", (name, content, "application/pdf")) for name, content in files]
    data = {"options": json.dumps(options if options is not None else {})}
    return client.post(f"/v1/tools/{tool}", files=multipart, data=data, headers=headers, params=params)


def wait_for_status(
    client: Any,
    job_id: str,
    wanted: tuple[str, ...] = ("done", "failed"),
    timeout: float = 20.0,
) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        response = client.get(f"/v1/jobs/{job_id}")
        last = response.json()
        if last.get("status") in wanted:
            return last
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach {wanted}; last answer: {last}")


def wait_until(predicate, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def jobs_dir(client: Any):
    return client.app.state.settings.work_dir / "jobs"
