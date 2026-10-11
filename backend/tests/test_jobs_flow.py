import io
import json
import time
import zipfile
from urllib.parse import unquote

from tests.helpers import jobs_dir, make_pdf, post_tool, wait_for_status, wait_until


def test_async_roundtrip_and_delete_after_download(client):
    pdf = make_pdf(2)
    created = post_tool(client, "selftest-copy", files=[("my report.pdf", pdf)])
    assert created.status_code == 202
    job_id = created.json()["job_id"]

    body = wait_for_status(client, job_id)
    assert body["status"] == "done"
    assert body["progress"] == 100
    assert body["result_size"] == len(pdf)
    assert body["result_name"] == "my report_copy.pdf"

    result = client.get(f"/v1/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.content == pdf
    assert result.headers["content-type"] == "application/pdf"
    assert "my report_copy.pdf" in unquote(result.headers["content-disposition"])
    assert json.loads(result.headers["x-result-meta"])["input_bytes"] == len(pdf)

    # The job and its files are deleted right after the download.
    assert wait_until(lambda: client.get(f"/v1/jobs/{job_id}").status_code == 410)
    assert client.get(f"/v1/jobs/{job_id}").json()["error"]["code"] == "job_expired"
    assert wait_until(lambda: not (jobs_dir(client) / job_id).exists())


def test_fast_tool_returns_the_file_directly(client):
    pdf = make_pdf(1)
    response = post_tool(client, "selftest-copy", files=[("a.pdf", pdf)], params={"wait": "true"})
    assert response.status_code == 200
    assert response.content == pdf
    assert response.headers["content-type"] == "application/pdf"


def test_non_fast_tool_ignores_wait(client):
    response = post_tool(client, "selftest-multi", params={"wait": "true"})
    assert response.status_code == 202
    assert "job_id" in response.json()


def test_several_outputs_are_zipped(client):
    job_id = post_tool(client, "selftest-multi").json()["job_id"]
    body = wait_for_status(client, job_id)
    assert body["status"] == "done"
    assert body["result_name"] == "parts.zip"
    result = client.get(f"/v1/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.headers["content-type"] == "application/zip"
    assert "parts.zip" in result.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(result.content))
    assert archive.namelist() == ["part-1.pdf", "part-2.pdf"]


def test_failed_job_reports_a_friendly_error(client):
    job_id = post_tool(client, "selftest-fail").json()["job_id"]
    body = wait_for_status(client, job_id)
    assert body["status"] == "failed"
    assert body["error"]["code"] == "wrong_password"
    assert body["error"]["message"]
    result = client.get(f"/v1/jobs/{job_id}/result")
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "wrong_password"
    client.delete(f"/v1/jobs/{job_id}")


def test_worker_crash_is_reported(client):
    job_id = post_tool(client, "selftest-crash").json()["job_id"]
    body = wait_for_status(client, job_id)
    assert body["status"] == "failed"
    assert body["error"]["code"] == "worker_crashed"


def test_hard_timeout_kills_the_worker(make_client):
    c = make_client(job_timeout_sec=1)
    job_id = post_tool(c, "selftest-sleep", options={"seconds": 30}).json()["job_id"]
    body = wait_for_status(c, job_id)
    assert body["status"] == "failed"
    assert body["error"]["code"] == "job_timeout"


def test_cancel_running_job_frees_the_slot(client):
    job_id = post_tool(client, "selftest-sleep", options={"seconds": 30}).json()["job_id"]
    wait_for_status(client, job_id, wanted=("processing",))
    assert client.delete(f"/v1/jobs/{job_id}").status_code == 204
    gone = client.get(f"/v1/jobs/{job_id}")
    assert gone.status_code == 410
    assert wait_until(lambda: not (jobs_dir(client) / job_id).exists())

    # With MAX_CONCURRENT_JOBS=1 this only works if the cancelled job released its slot.
    next_id = post_tool(client, "selftest-copy").json()["job_id"]
    assert wait_for_status(client, next_id)["status"] == "done"


def test_delete_is_idempotent_and_unknown_ids_404(client):
    assert client.delete("/v1/jobs/" + "0" * 32).status_code == 204
    missing = client.get("/v1/jobs/" + "0" * 32)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "job_not_found"
    assert client.get("/v1/jobs/short").status_code == 404


def test_result_not_ready_while_running(client):
    job_id = post_tool(client, "selftest-sleep", options={"seconds": 30}).json()["job_id"]
    wait_for_status(client, job_id, wanted=("processing",))
    response = client.get(f"/v1/jobs/{job_id}/result")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "result_not_ready"
    client.delete(f"/v1/jobs/{job_id}")


def test_queue_position_and_server_busy(make_client):
    c = make_client(max_queue=1)
    first = post_tool(c, "selftest-sleep", options={"seconds": 30}).json()["job_id"]
    wait_for_status(c, first, wanted=("processing",))

    second = post_tool(c, "selftest-sleep", options={"seconds": 30})
    assert second.status_code == 202
    queued = c.get(f"/v1/jobs/{second.json()['job_id']}").json()
    assert queued["status"] == "queued"
    assert queued["queue_position"] == 1

    third = post_tool(c, "selftest-sleep", options={"seconds": 30})
    assert third.status_code == 503
    assert third.json()["error"]["code"] == "server_busy"
    assert third.headers["retry-after"] == "30"


def test_expired_jobs_are_swept_by_the_janitor(client):
    job_id = post_tool(client, "selftest-copy").json()["job_id"]
    assert wait_for_status(client, job_id)["status"] == "done"
    assert (jobs_dir(client) / job_id).exists()

    client.app.state.manager._jobs[job_id].expires_at = time.monotonic() - 1

    assert client.get(f"/v1/jobs/{job_id}").status_code == 410
    assert wait_until(lambda: not (jobs_dir(client) / job_id).exists(), timeout=10)
    assert client.get(f"/v1/jobs/{job_id}/result").json()["error"]["code"] == "job_expired"
