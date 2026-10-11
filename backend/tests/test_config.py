from app.config import Settings

_NAMES = [
    "MAX_FILE_MB",
    "MAX_JOB_MB",
    "MAX_CONCURRENT_JOBS",
    "JOB_TTL_MIN",
    "JOB_TIMEOUT_SEC",
    "RATE_LIMIT_PER_HOUR",
    "OCR_MAX_PAGES",
]


def _clear(monkeypatch):
    for name in _NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_match_the_brief(monkeypatch):
    _clear(monkeypatch)
    s = Settings.from_env()
    assert (s.max_file_mb, s.max_job_mb, s.max_concurrent_jobs) == (25, 60, 1)
    assert (s.job_ttl_min, s.job_timeout_sec, s.rate_limit_per_hour, s.ocr_max_pages) == (45, 120, 30, 30)


def test_bad_values_fall_back_to_defaults(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("MAX_FILE_MB", "abc")
    monkeypatch.setenv("JOB_TIMEOUT_SEC", "")
    s = Settings.from_env()
    assert s.max_file_mb == 25
    assert s.job_timeout_sec == 120


def test_job_limit_is_never_below_file_limit(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("MAX_FILE_MB", "40")
    monkeypatch.setenv("MAX_JOB_MB", "10")
    s = Settings.from_env()
    assert s.max_job_mb == 40
