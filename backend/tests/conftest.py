from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def make_client(tmp_path):
    """Factory: make_client(max_queue=1, ...) starts a fresh app (with its lifespan) per call."""
    started: list[TestClient] = []

    def factory(**overrides):
        values = dict(
            work_dir=tmp_path / "work",
            enable_selftest_tools=True,
            worker_memory_mb=0,
            min_free_disk_mb=0,
            janitor_interval_sec=1,
        )
        values.update(overrides)
        client = TestClient(create_app(Settings(**values)))
        client.__enter__()
        started.append(client)
        return client

    yield factory
    for client in reversed(started):
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()
