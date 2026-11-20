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
    assert "AI TRADER HQ" in client.get("/", auth=a).text
    assert "class Person" in client.get("/static/hq.js").text
    assert "AI TRADER" in client.get("/terminal", auth=a).text
    ov = client.get("/api/overview", auth=a).json()
    assert ov["bot_up"] is False and ov["open_trades"] == []
    for path in ("/api/trades", "/api/strategies", "/api/research", "/api/market",
                 "/api/learnings", "/api/events", "/api/health"):
        r = client.get(path, auth=a)
        assert r.status_code == 200, path
    assert client.get("/api/lab/state").status_code == 401
    assert client.post("/api/lab/import", json={}, headers={"Authorization": "Bearer junk"}).status_code == 401
    g = client.get("/api/goals", auth=a).json()
    assert g["mission"] and len(g["goals"]) >= 5
    assert client.get("/api/candles", params={"pair": "BTC/USDT:USDT"}, auth=a).json()["candles"] == []
    assert client.post("/api/control/pause_research", auth=a).json()["ok"]
    assert client.get("/api/research", auth=a).json()["paused"] is True
