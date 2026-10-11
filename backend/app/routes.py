"""HTTP API: health, tool list, create job, poll job, download result, delete job."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect

from app.config import Settings
from app.errors import AppError
from app.jobs import JOB_ERROR_STATUS, Job, JobManager
from app.middleware import BodyTooLarge
from app.security import client_ip, detect_file_type, parse_device_id, sanitize_filename
from app.tools.catalog import ToolSpec, get_tool, list_tools

log = logging.getLogger("pdftoolkit.api")

router = APIRouter(prefix="/v1")

_CHUNK = 1024 * 1024
_MAX_OPTIONS_CHARS = 20_000
_KIND_LABELS = {"pdf": "PDF", "image": "image", "office": "Office", "html": "HTML"}


# ---------------------------------------------------------------------- helpers


def _files_message(spec: ToolSpec) -> str:
    if spec.min_files == spec.max_files:
        count = spec.min_files
        return f"This tool needs exactly {count} file{'s' if count != 1 else ''}."
    return f"This tool needs between {spec.min_files} and {spec.max_files} files."


def _unsupported_message(spec: ToolSpec) -> str:
    labels = " or ".join(_KIND_LABELS.get(kind, kind) for kind in spec.accepts)
    return f"This tool only accepts {labels} files."


def _file_too_large(settings: Settings) -> AppError:
    return AppError(413, "file_too_large", f"One of the files is larger than the {settings.max_file_mb} MB limit.")


def _job_too_large(settings: Settings) -> AppError:
    return AppError(413, "job_too_large", f"The files together are larger than the {settings.max_job_mb} MB limit.")


def _enforce_rate_limit(request: Request) -> None:
    state = request.app.state
    ip = client_ip(request, state.settings.trust_proxy)
    device = parse_device_id(request.headers.get("x-device-id"))
    wait = state.limiter_ip.acquire([f"ip:{ip}"])
    if not wait:
        wait = state.limiter_dev.acquire([f"dev:{device}" if device else f"nodev:{ip}"])
    if wait:
        minutes = max(1, math.ceil(wait / 60))
        raise AppError(
            429,
            "rate_limited",
            f"You have made a lot of requests. Please try again in about {minutes} minute{'s' if minutes != 1 else ''}.",
            retry_after=wait,
        )


def _parse_options(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, str):
        raise AppError(400, "invalid_options")
    if not raw.strip():
        return {}
    if len(raw) > _MAX_OPTIONS_CHARS:
        raise AppError(400, "invalid_options")
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise AppError(400, "invalid_options") from None
    if not isinstance(parsed, dict):
        raise AppError(400, "invalid_options")
    return parsed


async def _save_uploads(
    uploads: list[UploadFile], spec: ToolSpec, in_dir: Path, settings: Settings
) -> list[dict[str, str]]:
    """Stream every upload to disk as f0.pdf, f1.jpg, ... (original names are kept in memory only)."""
    inputs: list[dict[str, str]] = []
    total = 0
    for index, upload in enumerate(uploads):
        if upload.size is not None and upload.size > settings.max_file_bytes:
            raise _file_too_large(settings)
        header = await upload.read(2048)
        if not header:
            raise AppError(400, "corrupted_file", "One of the files is empty.")
        detected = detect_file_type(header)
        if detected is None or detected.kind not in spec.accepts:
            raise AppError(415, "unsupported_type", _unsupported_message(spec))
        path = in_dir / f"f{index}{detected.ext}"
        size = 0
        with open(path, "wb") as out:
            chunk = header
            while chunk:
                size += len(chunk)
                if size > settings.max_file_bytes:
                    raise _file_too_large(settings)
                if total + size > settings.max_job_bytes:
                    raise _job_too_large(settings)
                await asyncio.to_thread(out.write, chunk)
                chunk = await upload.read(_CHUNK)
        total += size
        name = sanitize_filename(upload.filename, f"file-{index + 1}{detected.ext}")
        inputs.append({"path": str(path), "name": name, "kind": detected.kind})
    return inputs


async def _serve_result(manager: JobManager, job: Job, *, consume_failure: bool) -> Response:
    """Return the finished file (and delete the job afterwards), or the job's error."""
    if job.cancelled:
        raise AppError(410, "job_expired")
    if job.status == "failed":
        error = job.error or {}
        code = error.get("code", "processing_failed")
        failure = AppError(JOB_ERROR_STATUS.get(code, 422), code, error.get("message"))
        if consume_failure:
            await manager.remove_job(job.id)
        raise failure
    if job.status != "done":
        raise AppError(409, "result_not_ready")
    if job.result_path is None or not job.result_path.is_file():
        raise AppError(410, "job_expired")

    headers: dict[str, str] = {}
    if job.meta:
        meta_text = json.dumps(job.meta, separators=(",", ":"))  # ASCII-only by default
        if len(meta_text) <= 2000:
            headers["X-Result-Meta"] = meta_text
    return FileResponse(
        job.result_path,
        media_type=job.result_mime,
        filename=job.result_name,
        headers=headers,
        background=BackgroundTask(manager.remove_job, job.id),  # delete right after download
    )


# ---------------------------------------------------------------------- routes


@router.get("/health")
async def health() -> dict[str, str]:
    """Instant and dependency-free: the app uses it to wake a sleeping free-tier server."""
    return {"status": "ok"}


@router.get("/tools")
async def tools(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return {
        "tools": [
            {
                "name": t.name,
                "accepts": list(t.accepts),
                "min_files": t.min_files,
                "max_files": t.max_files,
                "fast": t.fast,
            }
            for t in list_tools(include_internal=settings.enable_selftest_tools)
        ],
        "limits": {
            "max_file_mb": settings.max_file_mb,
            "max_job_mb": settings.max_job_mb,
            "job_ttl_min": settings.job_ttl_min,
            "ocr_max_pages": settings.ocr_max_pages,
        },
    }


@router.post("/tools/{tool}", response_model=None)
async def run_tool(tool: str, request: Request) -> Response:
    state = request.app.state
    settings: Settings = state.settings
    manager: JobManager = state.manager

    spec = get_tool(tool, include_internal=settings.enable_selftest_tools)
    if spec is None:
        raise AppError(404, "unknown_tool")
    _enforce_rate_limit(request)
    manager.check_capacity()
    wait_requested = request.query_params.get("wait", "").lower() in {"1", "true", "yes"}

    job_id = manager.new_id()
    form = None
    accepted = False
    try:
        try:
            form = await request.form(max_files=60, max_fields=20)
            uploads = [item for item in form.getlist("files") if isinstance(item, UploadFile)]
            if not spec.min_files <= len(uploads) <= spec.max_files:
                raise AppError(400, "invalid_files", _files_message(spec))
            options = _parse_options(form.get("options"))
            job_dir = manager.make_dirs(job_id)
            inputs = await _save_uploads(uploads, spec, job_dir / "in", settings)
            job = manager.submit(spec, job_id, inputs, options)
            accepted = True
        except AppError:
            raise
        except BodyTooLarge:
            raise _job_too_large(settings) from None
        except ClientDisconnect:
            raise AppError(400, "invalid_request") from None
        except StarletteHTTPException:
            raise AppError(400, "invalid_request") from None
        except Exception as exc:  # noqa: BLE001 - report type only; never log file data
            log.error("upload failed: %s", type(exc).__name__)
            raise AppError(500, "internal_error") from None
    finally:
        if form is not None:
            await form.close()
        if not accepted:
            await asyncio.to_thread(shutil.rmtree, manager.job_dir(job_id), True)

    if wait_requested and spec.fast:
        try:
            await asyncio.wait_for(job.done_event.wait(), timeout=settings.fast_wait_sec)
        except TimeoutError:
            return JSONResponse({"job_id": job.id}, status_code=202)
        return await _serve_result(manager, job, consume_failure=True)
    return JSONResponse({"job_id": job.id}, status_code=202)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict[str, Any]:
    manager: JobManager = request.app.state.manager
    return manager.public(manager.lookup(job_id))


@router.get("/jobs/{job_id}/result", response_model=None)
async def get_result(job_id: str, request: Request) -> Response:
    manager: JobManager = request.app.state.manager
    job = manager.lookup(job_id)
    return await _serve_result(manager, job, consume_failure=False)


@router.delete("/jobs/{job_id}", status_code=204, response_model=None)
async def delete_job(job_id: str, request: Request) -> Response:
    """Cancel and delete. Always succeeds, even if the job is already gone."""
    manager: JobManager = request.app.state.manager
    await manager.remove_job(job_id)
    return Response(status_code=204)
