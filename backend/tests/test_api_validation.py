from tests.helpers import make_pdf, padded_pdf, post_tool

DEVICE_A = "11111111-1111-4111-8111-111111111111"
DEVICE_B = "22222222-2222-4222-8222-222222222222"


def test_health_is_instant_and_hardened(client):
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_unknown_route_uses_error_format(client):
    response = client.get("/v1/nothing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_unknown_tool(client):
    response = post_tool(client, "does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "unknown_tool"
    assert body["error"]["message"]


def test_selftest_tools_are_hidden_by_default(make_client):
    c = make_client(enable_selftest_tools=False)
    assert post_tool(c, "selftest-copy").status_code == 404
    names = {tool["name"] for tool in c.get("/v1/tools").json()["tools"]}
    assert not any(name.startswith("selftest-") for name in names)


def test_tool_list_exposes_limits(client):
    body = client.get("/v1/tools").json()
    assert body["limits"]["max_file_mb"] == 25
    assert "selftest-copy" in {t["name"] for t in body["tools"]}


def test_no_files(client):
    response = post_tool(client, "selftest-copy", files=[])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_files"


def test_too_many_files(client):
    files = [(f"{i}.pdf", make_pdf()) for i in range(4)]
    response = post_tool(client, "selftest-copy", files=files)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_files"


def test_text_file_is_rejected_by_magic_bytes(client):
    response = post_tool(client, "selftest-copy", files=[("fake.pdf", b"hello world, not a pdf")])
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_type"


def test_image_is_rejected_by_a_pdf_only_tool(client):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    response = post_tool(client, "selftest-copy", files=[("pic.png", png)])
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_type"


def test_empty_file(client):
    response = post_tool(client, "selftest-copy", files=[("empty.pdf", b"")])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "corrupted_file"


def test_options_must_be_a_json_object(client):
    files = [("files", ("a.pdf", make_pdf(), "application/pdf"))]
    broken = client.post("/v1/tools/selftest-copy", files=files, data={"options": "{not json"})
    assert broken.status_code == 400
    assert broken.json()["error"]["code"] == "invalid_options"
    as_list = client.post("/v1/tools/selftest-copy", files=files, data={"options": "[1, 2]"})
    assert as_list.status_code == 400
    assert as_list.json()["error"]["code"] == "invalid_options"


def test_single_file_over_the_file_limit(make_client):
    c = make_client(max_file_mb=1, max_job_mb=5)
    response = post_tool(c, "selftest-copy", files=[("big.pdf", padded_pdf(1_500_000))])
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_whole_body_over_the_job_limit(make_client):
    c = make_client(max_file_mb=1, max_job_mb=1)
    response = post_tool(c, "selftest-copy", files=[("big.pdf", padded_pdf(3_500_000))])
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "job_too_large"


def test_rate_limit_per_device(make_client):
    c = make_client(rate_limit_per_hour=2)
    headers = {"X-Device-Id": DEVICE_A}
    assert post_tool(c, "selftest-copy", headers=headers).status_code == 202
    assert post_tool(c, "selftest-copy", headers=headers).status_code == 202
    blocked = post_tool(c, "selftest-copy", headers=headers)
    assert blocked.status_code == 429
    error = blocked.json()["error"]
    assert error["code"] == "rate_limited"
    assert error["retry_after"] > 0
    assert int(blocked.headers["retry-after"]) > 0
    # Another device on the same IP still has its own allowance.
    assert post_tool(c, "selftest-copy", headers={"X-Device-Id": DEVICE_B}).status_code == 202
