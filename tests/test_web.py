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
    assert "class Person" in client.get("/static/hq-people.js").text
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
    # JS/CSS are gzipped since ae01b3d (they are re-validated on every load); other static files are not
    r = client.get("/static/control.js", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip"
    r = client.get("/static/explorer.html", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") is None
    assert iso()  # registry + app share the test data dir


def test_explorer_page_and_api(client):
    a = ("admin", "pw")
    assert client.get("/explorer").status_code == 401
    r = client.get("/explorer", auth=a)
    assert r.status_code == 200 and "База стратегий" in r.text
    out = client.get("/api/explorer", auth=a).json()
    assert "strategies" in out and "groups" in out
    assert client.get("/api/explorer/no-such-id", auth=a).status_code == 404
    c = client.get("/api/explorer/candles?pair=BTC/USDT:USDT&tf=4h", auth=a).json()
    assert c["candles"] == []  # bot down in tests → empty, not an error


def test_coin_desks_api_lists_best_and_takes_the_owners_choice(client):
    """Control room → Монеты: each coin's strategies with their live record in this experiment,
    the coin's list of best tested strategies, and the owner's choice from that list."""
    import aitrader.web.app as webapp
    from aitrader.registry import Registry
    from aitrader.util import iso
    reg = Registry(webapp.S.registry_path)
    a = ("admin", "pw")
    for sid, pnl, trades, dd in (("good", 300, 20, 0.03), ("ok", 200, 12, 0.05), ("thin", 900, 2, 0.01)):
        reg.upsert("experiments", {"id": f"x-{sid}", "created": iso(), "family": "rsi_revert", "spec": {}, "status": "done",
                                   "result": {"pair_stats": {"BTC/USDT:USDT": {"pnl": pnl, "trades": trades}},
                                              "oos": {"n_days": 360, "max_drawdown": dd, "profit_factor": 1.5}}})
        reg.upsert("strategies", {"id": sid, "experiment_id": f"x-{sid}", "family": "rsi_revert", "params": {"p": 1},
                                  "pairs": ["BTC/USDT:USDT"], "sides": ["long", "short"], "stage": "exploratory", "score": 1.0,
                                  "oos": {"timeframe": "1h", "profit_factor": 1.5}, "gates": {}, "live": {},
                                  "created": iso(), "updated": iso(), "stage_since": iso(), "history": []})
    reg.kv_set("desks", {"epoch": 1, "created": "2026-11-23T15:39:48Z", "cuts": [0.5, 1.5], "coins": {
        "BTC/USDT:USDT": {"pair": "BTC/USDT:USDT", "strategy": "good", "family": "rsi_revert", "timeframe": "1h",
                          "bucket": "active", "per_month": 1.7, "pnl_month": 25.0, "max_dd": 0.03}}})
    reg.upsert("live_trades", {"trade_id": 1, "sleeve_id": "good", "pair": "BTC/USDT:USDT", "is_short": 0,
                               "open_date": "2026-11-22T10:00:00Z", "close_date": "2026-11-22T12:00:00Z", "profit_abs": -9.0},
               key="trade_id")  # before the experiment: not counted
    reg.upsert("live_trades", {"trade_id": 2, "sleeve_id": "good", "pair": "BTC/USDT:USDT", "is_short": 1,
                               "open_date": "2026-11-23T18:00:00Z", "close_date": "2026-11-23T20:00:00Z", "profit_abs": 7.5},
               key="trade_id")
    names = client.get("/api/names", auth=a).json()
    assert names["good"]["code"] and names["good"]["method"].startswith("RSI")
    d = client.get("/api/desks", auth=a).json()
    btc = d["desks"][0]
    assert btc["coin"] == "BTC" and btc["picks"][0]["id"] == "good" and btc["picks"][0]["code"] == names["good"]["code"]
    assert btc["picks"][0]["demo"] == {"trades": 1, "pnl": 7.5, "pf": 99.0, "wins": 1}
    o = client.get("/api/desks/options", params={"pair": "BTC/USDT:USDT"}, auth=a).json()
    assert [x["id"] for x in o["options"]] == ["good", "ok"]  # "thin" has too few trades on BTC
    assert o["options"][0]["chosen"] and not o["options"][1]["chosen"]
    assert client.post("/api/desks/set", json={"pair": "BTC/USDT:USDT", "strategies": ["thin"]}, auth=a).status_code == 400
    r = client.post("/api/desks/set", json={"pair": "BTC/USDT:USDT", "strategies": ["ok", "good"]}, auth=a)
    assert r.status_code == 200 and [x["strategy"] for x in r.json()["desk"]["picks"]] == ["ok", "good"]
    st = {x["id"]: x["stage"] for x in reg.strategies()}
    assert st["ok"] == st["good"] == "exploration" and st["thin"] == "exploratory"
    assert [x["id"] for x in client.get("/api/desks", auth=a).json()["desks"][0]["picks"]] == ["ok", "good"]
    coins = client.get("/api/desks/coins", auth=a).json()["coins"]
    assert coins[0]["coin"] == "BTC" and coins[0]["options"] == 2 and coins[0]["desk"]
    ov = client.get("/api/overview", auth=a).json()
    assert ov["experiment"]["closed_count"] == 1 and ov["experiment"]["closed_pnl"] == 7.5
