"""Runtime configuration, read once from environment variables with safe defaults."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

_MB = 1024 * 1024

def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return max(value, minimum)

def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

def _env_list(name: str) -> tuple[str, ...]:
    """Comma-separated list; blanks and duplicates dropped, trailing slashes removed."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return ()
    items: list[str] = []
    for part in raw.split(","):
        item = part.strip().rstrip("/")
        if item and item not in items:
            items.append(item)
    return tuple(items)

@dataclass(frozen=True)
class Settings:
    # Where job files live (ephemeral). Only the "jobs" and "spool" subfolders are ever wiped.
    work_dir: Path = Path(tempfile.gettempdir()) / "pdf-toolkit"

    # Limits requested in the project brief.
    max_file_mb: int = 25
    max_job_mb: int = 60
    max_concurrent_jobs: int = 1
    job_ttl_min: int = 45
    job_timeout_sec: int = 120
    rate_limit_per_hour: int = 30  # 0 disables rate limiting
    ocr_max_pages: int = 30

    # Extra safety knobs.
    max_queue: int = 20  # jobs waiting in the queue
    max_total_jobs: int = 40  # jobs alive at once (queued + running + finished-not-downloaded)
    worker_memory_mb: int = 1024  # address-space limit per worker process (0 disables)
    worker_max_output_mb: int = 300  # largest file a worker may write (0 disables)
    fast_wait_sec: int = 20  # how long ?wait=true waits for a fast tool
    min_free_disk_mb: int = 200  # refuse new jobs below this much free disk
    janitor_interval_sec: int = 30
    trust_proxy: bool = True  # read client IP from X-Forwarded-For (Render sits behind a proxy)
    enable_selftest_tools: bool = False  # test-only tools; keep off in production
    enable_docs: bool = False  # expose /docs and /openapi.json
    cors_origins: tuple[str, ...] = ()  # allowed browser origins; empty = CORS disabled

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * _MB

    @property
    def max_job_bytes(self) -> int:
        return self.max_job_mb * _MB

    @property
    def max_body_bytes(self) -> int:
        # Whole multipart body: files plus a little framing overhead.
        return self.max_job_bytes + 2 * _MB

    @property
    def max_output_bytes(self) -> int:
        return self.worker_max_output_mb * _MB

    @property
    def ttl_sec(self) -> int:
        return self.job_ttl_min * 60

    @classmethod
    def from_env(cls) -> "Settings":
        max_file = _env_int("MAX_FILE_MB", 25, 1)
        max_job = max(_env_int("MAX_JOB_MB", 60, 1), max_file)
        work_dir = os.environ.get("WORK_DIR") or str(Path(tempfile.gettempdir()) / "pdf-toolkit")
        return cls(
            work_dir=Path(work_dir),
            max_file_mb=max_file,
            max_job_mb=max_job,
            max_concurrent_jobs=_env_int("MAX_CONCURRENT_JOBS", 1, 1),
            job_ttl_min=_env_int("JOB_TTL_MIN", 45, 1),
            job_timeout_sec=_env_int("JOB_TIMEOUT_SEC", 120, 1),
            rate_limit_per_hour=_env_int("RATE_LIMIT_PER_HOUR", 30, 0),
            ocr_max_pages=_env_int("OCR_MAX_PAGES", 30, 1),
            max_queue=_env_int("MAX_QUEUE", 20, 1),
            max_total_jobs=_env_int("MAX_TOTAL_JOBS", 40, 1),
            worker_memory_mb=_env_int("WORKER_MEMORY_MB", 1024, 0),
            worker_max_output_mb=_env_int("WORKER_MAX_OUTPUT_MB", 300, 0),
            fast_wait_sec=_env_int("FAST_WAIT_SEC", 20, 0),
            min_free_disk_mb=_env_int("MIN_FREE_DISK_MB", 200, 0),
            janitor_interval_sec=_env_int("JANITOR_INTERVAL_SEC", 30, 1),
            trust_proxy=_env_bool("TRUST_PROXY", True),
            enable_selftest_tools=_env_bool("ENABLE_SELFTEST_TOOLS", False),
            enable_docs=_env_bool("ENABLE_DOCS", False),
            cors_origins=_env_list("CORS_ORIGINS"),
        )
