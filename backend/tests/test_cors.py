from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ORIGIN = "https://app.example.com"
OTHER = "https://evil.example.org"

def _client(tmp_path, origins=()):
    settings = Settings(
        work_dir=tmp_path / "work",
        rate_limit_per_hour=0,
        worker_memory_mb=0,
        cors_origins=tuple(origins),
    )
    return TestClient(create_app(settings))

# ---------------------------------------------------------------- settings

def test_cors_is_off_by_default(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert Settings.from_env().cors_origins == ()
    assert Settings().cors_origins == ()

def test_cors_origins_env_is_parsed(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", " https://a.example.com/ ,https://b.example.com,, https://a.example.com ")
    assert Settings.from_env().cors_origins == ("https://a.example.com", "https://b.example.com")

def test_blank_cors_origins_env_means_off(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "   ")
    assert Settings.from_env().cors_origins == ()

# ---------------------------------------------------------------- disabled

def test_no_cors_headers_when_disabled(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/v1/health", headers={"Origin": ORIGIN})
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers
        preflight = client.options(
            "/v1/tools/rotate",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-device-id",
            },
        )
        assert "access-control-allow-origin" not in preflight.headers

# ---------------------------------------------------------------- enabled

def test_allowed_origin_gets_headers_and_exposed_headers(tmp_path):
    with _client(tmp_path, [ORIGIN]) as client:
        response = client.get("/v1/health", headers={"Origin": ORIGIN})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == ORIGIN
        exposed = response.headers["access-control-expose-headers"].lower()
        assert "content-disposition" in exposed
        assert "x-result-meta" in exposed

def test_preflight_allows_device_id_header_and_post(tmp_path):
    with _client(tmp_path, [ORIGIN]) as client:
        response = client.options(
            "/v1/tools/rotate",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-device-id",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert "x-device-id" in response.headers["access-control-allow-headers"].lower()
        assert "POST" in response.headers["access-control-allow-methods"]
        assert response.headers["access-control-max-age"] == "600"

def test_other_origin_is_not_allowed(tmp_path):
    with _client(tmp_path, [ORIGIN]) as client:
        response = client.get("/v1/health", headers={"Origin": OTHER})
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers
        preflight = client.options(
            "/v1/tools/rotate",
            headers={"Origin": OTHER, "Access-Control-Request-Method": "POST"},
        )
        assert preflight.status_code == 400
        assert "access-control-allow-origin" not in preflight.headers

def test_wildcard_origin(tmp_path):
    with _client(tmp_path, ["*"]) as client:
        response = client.get("/v1/health", headers={"Origin": OTHER})
        assert response.headers["access-control-allow-origin"] == "*"

def test_error_responses_carry_cors_headers(tmp_path):
    with _client(tmp_path, [ORIGIN]) as client:
        response = client.get("/v1/does-not-exist", headers={"Origin": ORIGIN})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert response.headers["access-control-allow-origin"] == ORIGIN
