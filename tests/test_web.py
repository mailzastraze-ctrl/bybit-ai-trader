"""Web terminal API (runs where fastapi+httpx exist, i.e. inside the freqtrade image in CI)."""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AITRADER_DATA", str(tmp_path))
    monkeypatch.setenv("WEB_PASSWORD", "pw")
    monkeypatch.setenv("FT_API_URL", "http://127.0.0.1:9")  # nothing listens → bot "down"
    import aitrader.settings as settings
    settings._settings = None
    import aitrader.web.app as webapp
    importlib.reload(webapp)
    from fastapi.testclient import TestClient
    return TestClient(webapp.app)


def test_auth_and_endpoints(client):
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/api/overview").status_code == 401
    assert client.get("/api/overview", auth=("admin", "wrong")).status_code == 401
    a = ("admin", "pw")
    assert "Пульт управления" in client.get("/", auth=a).text
    assert "AI TRADER HQ" in client.get("/hq", auth=a).text
    assert "renderForward" in client.get("/static/control.js").text
    assert "class Person" in client.get("/static/hq.js").text
    assert "Пульт управления" in client.get("/terminal", auth=a).text  # old page → the one control room
    ov = client.get("/api/overview", auth=a).json()
    assert ov["bot_up"] is False and ov["open_trades"] == []
    for path in ("/api/trades", "/api/strategies", "/api/research", "/api/market",
                 "/api/learnings", "/api/events", "/api/health", "/api/forward", "/api/goals", "/api/screen", "/api/cards"):
        r = client.get(path, auth=a)
        assert r.status_code == 200, path
    assert client.get("/api/lab/state").status_code == 401
    assert client.get("/api/lab/backup").status_code == 401
    assert client.get("/relay/https://api.bybit.com/v5/market/time").status_code == 401
    assert client.get("/api/readiness", auth=a).json()["total"] == 10  # + daily Newey–West t, alpha over BTC
    assert client.post("/api/lab/import", json={}, headers={"Authorization": "Bearer junk"}).status_code == 401
    g = client.get("/api/goals", auth=a).json()
    assert g["mission"] and len(g["goals"]) >= 5
    assert client.get("/api/candles", params={"pair": "BTC/USDT:USDT"}, auth=a).json()["candles"] == []
    assert client.post("/api/control/pause_research", auth=a).json()["ok"]
    assert client.get("/api/research", auth=a).json()["paused"] is True


def test_api_json_is_gzipped_static_is_not(client):
    """Railway bills egress: the JSON API (polled by the control room and the 3D office) and
    the lab relay are gzip-compressed; static assets and the registry backup are left alone."""
    import aitrader.web.app as webapp
    from aitrader.registry import Registry
    from aitrader.util import iso
    reg = Registry(webapp.S.registry_path)
    for i in range(400):  # enough events for a response well above the 1 KB threshold
        reg.event("test", f"event {i} " + "x" * 50)
    a = ("admin", "pw")
    r = client.get("/api/events?limit=300", auth=a, headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip" and len(r.json()) > 0
    r = client.get("/static/control.js", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") is None
    assert iso()  # registry + app share the test data dir
