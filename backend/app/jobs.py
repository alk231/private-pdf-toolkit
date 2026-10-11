"""In-process job manager: asyncio queue + semaphore, one worker subprocess per job, janitor.

Everything lives in memory (single instance). Files live under WORK_DIR/jobs/<job_id>/{in,out,tmp}.
Original file names never touch disk or logs; job options (passwords!) are passed to the worker
through stdin and dropped from memory as soon as the worker has started.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import sys
import time
import uuid
import zipfile
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.config import Settings
from app.errors import USER_MESSAGES, AppError
from app.security import sanitize_filename
from app.tools.catalog import ToolSpec

log = logging.getLogger("pdftoolkit.jobs")

BACKEND_DIR = Path(__file__).resolve().parent.parent  # the folder that contains the "app" package
_STREAM_LIMIT = 4 * 1024 * 1024  # longest line the worker may print (the RESULT line)
_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_MAX_TOMBSTONES = 5000
_ORPHAN_AGE_SEC = 600
_SPOOL_AGE_SEC = 3600
_HOUSEKEEPING_EVERY_SEC = 300
_STORED_SUFFIXES = {".jpg", ".jpeg", ".png", ".zip"}  # already compressed: do not deflate again

# HTTP status used when a failed job's error is returned as a response.
JOB_ERROR_STATUS: dict[str, int] = {
    "invalid_options": 400,
    "wrong_password": 422,
    "password_required": 422,
    "corrupted_file": 422,
    "too_complex": 422,
    "output_too_large": 422,
    "processing_failed": 422,
    "job_timeout": 504,
    "worker_crashed": 500,
    "internal_error": 500,
}


def _failure(code: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "message": USER_MESSAGES.get(code, USER_MESSAGES["processing_failed"])}


def _code_for_exit(returncode: int | None) -> str:
    if returncode is not None and returncode < 0:
        sig = -returncode
        if sig == int(signal.SIGXCPU):
            return "job_timeout"
        if sig == int(signal.SIGXFSZ):
            return "output_too_large"
        if sig == int(signal.SIGKILL):  # usually the kernel's out-of-memory killer
            return "too_complex"
    return "worker_crashed"


def _make_zip(zip_path: Path, files: list[tuple[Path, str, str]]) -> None:
    used: set[str] = set()
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path, name, _mime in files:
            arcname = name
            counter = 1
            while arcname.lower() in used:
                counter += 1
                stem, ext = os.path.splitext(name)
                arcname = f"{stem} ({counter}){ext}"
            used.add(arcname.lower())
            method = zipfile.ZIP_STORED if path.suffix.lower() in _STORED_SUFFIXES else zipfile.ZIP_DEFLATED
            archive.write(path, arcname=arcname, compress_type=method)
    for path, _name, _mime in files:
        path.unlink(missing_ok=True)


@dataclass
class Job:
    id: str
    tool: str
    dir: Path
    timeout: int
    spec: dict[str, Any] | None
    created_at: float
    expires_at: float
    status: str = "queued"  # queued | processing | done | failed
    progress: int = 0
    error: dict[str, str] | None = None
    result_path: Path | None = None
    result_name: str = "result"
    result_mime: str = "application/octet-stream"
    result_size: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False
    proc: asyncio.subprocess.Process | None = None
    done_event: asyncio.Event = field(default_factory=asyncio.Event)


class JobManager:
    def __init__(self, settings: Settings, housekeeping: Callable[[], None] | None = None) -> None:
        self.settings = settings
        self.jobs_dir = settings.work_dir / "jobs"
        self.spool_dir = settings.work_dir / "spool"
        self._housekeeping = housekeeping
        self._jobs: dict[str, Job] = {}
        self._tombstones: OrderedDict[str, float] = OrderedDict()
        self._queue: asyncio.Queue[Job] | None = None
        self._sem: asyncio.Semaphore | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._dispatcher: asyncio.Task[None] | None = None
        self._janitor: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ lifecycle

    def prepare_dirs(self) -> None:
        """Start from an empty workspace (the disk is ephemeral anyway)."""
        for directory in (self.jobs_dir, self.spool_dir):
            shutil.rmtree(directory, ignore_errors=True)
            directory.mkdir(parents=True, exist_ok=True)

    async def start(self) -> None:
        self.prepare_dirs()
        self._queue = asyncio.Queue()
        self._sem = asyncio.Semaphore(self.settings.max_concurrent_jobs)
        self._dispatcher = asyncio.create_task(self._dispatch_loop())
        self._janitor = asyncio.create_task(self._janitor_loop())

    async def stop(self) -> None:
        background: list[asyncio.Task[None]] = [t for t in (self._dispatcher, self._janitor) if t is not None]
        for job in list(self._jobs.values()):
            job.cancelled = True
            if job.proc is not None:
                self._kill(job.proc)
        background.extend(self._tasks)
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        self._jobs.clear()
        shutil.rmtree(self.jobs_dir, ignore_errors=True)
        shutil.rmtree(self.spool_dir, ignore_errors=True)

    # ------------------------------------------------------------------ public API (called by routes)

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def make_dirs(self, job_id: str) -> Path:
        base = self.job_dir(job_id)
        for name in ("in", "out", "tmp"):
            (base / name).mkdir(parents=True, exist_ok=True)
        return base

    def queued_count(self) -> int:
        return sum(1 for job in self._jobs.values() if job.status == "queued")

    def check_capacity(self) -> None:
        if len(self._jobs) >= self.settings.max_total_jobs or self.queued_count() >= self.settings.max_queue:
            raise AppError(503, "server_busy", retry_after=30)
        try:
            free_mb = shutil.disk_usage(self.settings.work_dir).free // (1024 * 1024)
        except OSError:
            return
        if free_mb < self.settings.min_free_disk_mb:
            raise AppError(503, "server_busy", retry_after=60)

    def submit(self, tool: ToolSpec, job_id: str, inputs: list[dict[str, str]], options: dict[str, Any]) -> Job:
        self.check_capacity()
        if self._queue is None:
            raise AppError(503, "server_busy", retry_after=5)
        base = self.job_dir(job_id)
        timeout = max(1, int(self.settings.job_timeout_sec * tool.timeout_factor))
        memory_mb = tool.memory_mb if tool.memory_mb is not None else self.settings.worker_memory_mb
        spec = {
            "tool": tool.name,
            "inputs": inputs,
            "options": options,
            "out_dir": str(base / "out"),
            "tmp_dir": str(base / "tmp"),
            "limits": {
                "memory_mb": memory_mb,
                "max_output_mb": self.settings.worker_max_output_mb,
                "cpu_sec": timeout * 2,
                "ocr_max_pages": self.settings.ocr_max_pages,
            },
        }
        now = time.monotonic()
        job = Job(
            id=job_id,
            tool=tool.name,
            dir=base,
            timeout=timeout,
            spec=spec,
            created_at=now,
            expires_at=now + self.settings.ttl_sec,
        )
        self._jobs[job_id] = job
        self._queue.put_nowait(job)
        log.info("job %s queued tool=%s files=%d", job_id, tool.name, len(inputs))
        return job

    def lookup(self, job_id: str) -> Job:
        job = self._jobs.get(job_id) if _JOB_ID_RE.match(job_id) else None
        if job is None:
            if job_id in self._tombstones:
                raise AppError(410, "job_expired")
            raise AppError(404, "job_not_found")
        if job.cancelled or (job.status != "processing" and time.monotonic() >= job.expires_at):
            raise AppError(410, "job_expired")
        return job

    def public(self, job: Job) -> dict[str, Any]:
        body: dict[str, Any] = {
            "job_id": job.id,
            "status": job.status,
            "progress": 100 if job.status == "done" else job.progress,
        }
        if job.status == "queued":
            body["queue_position"] = self._queue_position(job)
        if job.status == "failed" and job.error:
            body["error"] = job.error
        if job.status == "done":
            body["result_size"] = job.result_size
            body["result_name"] = job.result_name
            body["meta"] = job.meta
        body["expires_in"] = max(0, int(job.expires_at - time.monotonic()))
        return body

    async def remove_job(self, job_id: str) -> None:
        """Cancel (if running) and delete a job and all of its files. Safe to call twice."""
        job = self._jobs.pop(job_id, None)
        if job is None:
            return
        self._tombstone(job_id)
        job.cancelled = True
        if job.proc is not None:
            self._kill(job.proc)
        job.done_event.set()
        if job.status != "processing":
            await asyncio.to_thread(shutil.rmtree, job.dir, True)
        # A processing job is cleaned up by _run() as soon as the killed worker exits.

    # ------------------------------------------------------------------ internals

    def _queue_position(self, job: Job) -> int:
        return 1 + sum(1 for j in self._jobs.values() if j.status == "queued" and j.created_at < job.created_at)

    def _tombstone(self, job_id: str) -> None:
        self._tombstones[job_id] = time.monotonic()
        self._tombstones.move_to_end(job_id)
        while len(self._tombstones) > _MAX_TOMBSTONES:
            self._tombstones.popitem(last=False)

    @staticmethod
    def _kill(proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # the worker leads its own process group
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    async def _dispatch_loop(self) -> None:
        assert self._queue is not None and self._sem is not None
        while True:
            job = await self._queue.get()
            await self._sem.acquire()
            if job.cancelled or self._jobs.get(job.id) is not job or job.status != "queued":
                self._sem.release()
                continue
            job.status = "processing"
            task = asyncio.create_task(self._run(job))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _discard(self, job: Job) -> None:
        await asyncio.to_thread(shutil.rmtree, job.dir, True)

    async def _run(self, job: Job) -> None:
        started = time.monotonic()
        try:
            spec = job.spec or {}
            job.spec = None  # options (e.g. passwords) are no longer kept in the registry
            if job.cancelled:
                await self._discard(job)
                return
            try:
                outcome = await self._execute(job, spec)
            except Exception as exc:  # noqa: BLE001 - never let one job break the manager
                log.error("job %s could not run: %s", job.id, type(exc).__name__)
                outcome = _failure("internal_error")
            spec = {}
            if job.cancelled:
                await self._discard(job)
                return

            if outcome.get("ok"):
                try:
                    await self._finalize(job, outcome)
                except Exception as exc:  # noqa: BLE001
                    log.error("job %s finalize failed: %s", job.id, type(exc).__name__)
                    outcome = _failure("processing_failed")
                if job.cancelled:
                    await self._discard(job)
                    return

            if outcome.get("ok"):
                job.status = "done"
                job.progress = 100
            else:
                job.status = "failed"
                job.error = {
                    "code": str(outcome.get("code") or "processing_failed"),
                    "message": str(outcome.get("message") or USER_MESSAGES["processing_failed"]),
                }
            job.expires_at = time.monotonic() + self.settings.ttl_sec
            await asyncio.to_thread(self._cleanup, job)
            log.info(
                "job %s tool=%s status=%s ms=%d",
                job.id,
                job.tool,
                job.status,
                int((time.monotonic() - started) * 1000),
            )
        finally:
            job.proc = None
            job.done_event.set()
            if self._sem is not None:
                self._sem.release()

    def _cleanup(self, job: Job) -> None:
        """Inputs and scratch files are always deleted; outputs only when the job did not succeed."""
        shutil.rmtree(job.dir / "in", ignore_errors=True)
        shutil.rmtree(job.dir / "tmp", ignore_errors=True)
        if job.status != "done":
            shutil.rmtree(job.dir / "out", ignore_errors=True)

    async def _execute(self, job: Job, spec: dict[str, Any]) -> dict[str, Any]:
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["TMPDIR"] = str(spec.get("tmp_dir") or (job.dir / "tmp"))
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(BACKEND_DIR),
            env=env,
            start_new_session=True,
            limit=_STREAM_LIMIT,
        )
        job.proc = proc
        try:
            if job.cancelled:
                self._kill(proc)
            if proc.stdin is not None:
                try:
                    proc.stdin.write(json.dumps(spec).encode("utf-8"))
                    await proc.stdin.drain()
                    proc.stdin.close()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            try:
                result = await asyncio.wait_for(self._pump(proc, job), timeout=job.timeout)
            except TimeoutError:
                self._kill(proc)
                await proc.wait()
                return _failure("job_timeout")
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except TimeoutError:
                self._kill(proc)
                await proc.wait()
            if result is not None:
                return result
            return _failure(_code_for_exit(proc.returncode))
        finally:
            if proc.returncode is None:
                self._kill(proc)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except TimeoutError:
                    pass

    async def _pump(self, proc: asyncio.subprocess.Process, job: Job) -> dict[str, Any] | None:
        """Read PROGRESS / RESULT lines from the worker until it closes its channel."""
        assert proc.stdout is not None
        result: dict[str, Any] | None = None
        while True:
            try:
                line = await proc.stdout.readline()
            except ValueError:  # a line longer than the stream limit
                return None
            if not line:
                break
            tag, _, payload = line.decode("utf-8", "replace").strip().partition(" ")
            if tag == "PROGRESS":
                try:
                    job.progress = max(job.progress, min(int(payload), 99))
                except ValueError:
                    pass
            elif tag == "RESULT":
                try:
                    parsed = json.loads(payload)
                except ValueError:
                    parsed = None
                if isinstance(parsed, dict):
                    result = parsed
        return result

    async def _finalize(self, job: Job, outcome: dict[str, Any]) -> None:
        """Validate the worker's outputs and, for several files, bundle them into one zip."""
        out_root = (job.dir / "out").resolve()
        files: list[tuple[Path, str, str]] = []
        for item in outcome.get("outputs") or []:
            path = Path(str(item["path"])).resolve()
            if out_root not in path.parents or not path.is_file():
                raise ValueError("bad output path")
            name = sanitize_filename(str(item.get("name") or ""), "result")
            mime = str(item.get("mime") or "application/octet-stream")
            files.append((path, name, mime))
        if not files:
            raise ValueError("no outputs")

        if len(files) == 1:
            path, name, mime = files[0]
        else:
            name = sanitize_filename(str(outcome.get("zip_name") or "result.zip"), "result.zip")
            if not name.lower().endswith(".zip"):
                name += ".zip"
            path = job.dir / "result.zip"
            await asyncio.to_thread(_make_zip, path, files)
            mime = "application/zip"

        job.result_path = path
        job.result_name = name
        job.result_mime = mime
        job.result_size = path.stat().st_size
        meta = outcome.get("meta")
        job.meta = meta if isinstance(meta, dict) else {}

    # ------------------------------------------------------------------ janitor

    async def _janitor_loop(self) -> None:
        last_housekeeping = time.monotonic()
        while True:
            await asyncio.sleep(self.settings.janitor_interval_sec)
            try:
                await self._sweep()
                now = time.monotonic()
                if self._housekeeping is not None and now - last_housekeeping >= _HOUSEKEEPING_EVERY_SEC:
                    self._housekeeping()
                    last_housekeeping = now
            except Exception as exc:  # noqa: BLE001 - the janitor must never die
                log.error("janitor error: %s", type(exc).__name__)

    async def _sweep(self) -> None:
        now = time.monotonic()
        for job in list(self._jobs.values()):
            if job.status != "processing" and now >= job.expires_at:
                await self.remove_job(job.id)
        known = set(self._jobs)
        await asyncio.to_thread(self._scan_orphans, self.jobs_dir, known, _ORPHAN_AGE_SEC)
        await asyncio.to_thread(self._scan_orphans, self.spool_dir, set(), _SPOOL_AGE_SEC)

    @staticmethod
    def _scan_orphans(directory: Path, known: set[str], max_age_sec: int) -> None:
        """Delete leftovers nobody owns any more (for example after a failed delete)."""
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        now = time.time()
        for entry in entries:
            if entry.name in known:
                continue
            try:
                if now - entry.stat().st_mtime <= max_age_sec:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(entry.path, ignore_errors=True)
                else:
                    os.unlink(entry.path)
            except OSError:
                continue
