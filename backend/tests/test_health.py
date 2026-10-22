from datetime import datetime

from fastapi.testclient import TestClient

from app import __version__
from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/api/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["service"]
    assert body["version"] == __version__
    assert body["environment"]
    assert body["data_mode"] == "synthetic"


def test_health_time_is_timezone_aware():
    body = client.get("/api/health").json()
    server_time = datetime.fromisoformat(body["server_time_utc"].replace("Z", "+00:00"))
    assert server_time.tzinfo is not None
    assert server_time.utcoffset().total_seconds() == 0


def test_cors_allows_configured_frontend_origin():
    response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_unknown_origin():
    response = client.get("/api/health", headers={"Origin": "http://evil.example.com"})
    assert "access-control-allow-origin" not in response.headers


def test_unknown_route_returns_404():
    assert client.get("/api/does-not-exist").status_code == 404
