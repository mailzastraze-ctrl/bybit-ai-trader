"""Disk breakdown, growth forecast, health line and red flags (observation only, 2026-11-22)."""

from datetime import timedelta

from aitrader import observe, storage
from aitrader.registry import Registry
from aitrader.util import iso, utcnow


def test_disk_breakdown_growth_and_wal_checkpoint(tmp_path):
    data = tmp_path / "data"
    (data / "aitrader").mkdir(parents=True)
    (data / "user_data" / "logs").mkdir(parents=True)
    (data / "user_data" / "logs" / "freqtrade.log").write_bytes(b"x" * 3 * 2**20)
    reg = Registry(data / "aitrader" / "registry.sqlite")
    reg.kv_set("blob", "y" * 2**20)
    b = storage.disk_breakdown(data, data / "aitrader" / "registry.sqlite")
    assert b["folders_mb"]["user_data/logs"] == 3.0 and b["largest"][0]["file"].endswith("freqtrade.log")
    assert b["registry"]["main_mb"] >= 0
    t = storage.table_sizes(data / "aitrader" / "registry.sqlite")
    assert t.get("kv", 0) >= 0.9
    now = utcnow()
    hist = [{"ts": iso(now - timedelta(days=1)), "used_mb": 220}, {"ts": iso(now), "used_mb": 365}]
    g = storage.growth(hist, {"free_mb": 1450})
    assert g["mb_per_day"] == 145.0 and g["days_to_full"] == 10.0
    out = storage.disk_tick(reg, data, data / "aitrader" / "registry.sqlite")
    assert "breakdown" in out and "tables_mb" in out and reg.kv_get("disk_hist")
    storage.maintain(reg, data, None)  # the daily maintenance keeps the breakdown
    assert "breakdown" in reg.kv_get("disk")


def test_health_counts_positions_without_exchange_stop():
    now = utcnow()
    old, young = iso(now - timedelta(hours=2)), iso(now - timedelta(seconds=30))
    trades = [
        {"pair": "XRP/USDT:USDT", "open_date": old, "open_rate": 1.0, "stop_loss_abs": 0.98, "stake_amount": 1000,
         "orders": [{"ft_order_side": "stoploss", "status": "open"}]},
        {"pair": "ETH/USDT:USDT", "open_date": old, "open_rate": 100.0, "stop_loss_abs": 97, "stake_amount": 1000,
         "orders": [{"ft_order_side": "buy", "status": "closed"}]},
        {"pair": "SOL/USDT:USDT", "open_date": young, "orders": []},  # just opened: stop on its way
    ]
    h = observe.health(trades, 50_000, now)
    assert h["positions"] == 3 and h["no_exchange_stop"] == ["ETH/USDT:USDT"]
    assert h["risk_pct"] == round(100 * (20 + 30) / 50_000, 2)


def test_red_flags_and_status_line(tmp_path):
    reg = Registry(tmp_path / "r.db")
    reg.heartbeat("manager", "ok", {})
    reg.kv_set("lab", {"last_import": iso(), "last_batch_total": 42, "last_batch_failed": 0})
    reg.kv_set("disk", {"free_pct": 0.78, "free_mb": 1560, "growth": {"mb_per_day": 145.0, "days_to_full": 10.8}})
    reg.kv_set("health", {"positions": 8, "no_exchange_stop": [], "risk_pct": 2.1})
    flags = observe.red_flags(reg)
    assert flags == ["disk full in ~11 d"]
    reg.kv_set("parity", {"alarm": True, "like_for_like": False})  # old-style comparison: not a red flag
    reg.kv_set("lab", {"last_import": iso(utcnow() - timedelta(hours=30)), "last_batch_total": 40, "last_batch_failed": 10})
    flags = observe.red_flags(reg)
    assert "lab import > 24h" in flags and "lab failures 10/40" in flags and "PARITY ALARM" not in flags
    line = observe.status_line(reg)
    assert line.startswith("HEALTH positions=8") and "full in 11 d" in line and "lab import > 24h" in line


# ---------------------------------------------------------------- janitor (2026-11-22)
def _old(p, days):
    import os
    import time
    t = time.time() - days * 86400
    os.utime(p, (t, t))


def _settings(tmp_path, mode="remote"):
    from pathlib import Path

    from aitrader.settings import Settings
    s = Settings(data_dir=tmp_path / "data", app_dir=Path(__file__).resolve().parents[1])
    s.research.mode = mode
    s.ensure_dirs()
    return s


def test_janitor_removes_stale_files_and_keeps_live_ones(tmp_path, monkeypatch):
    import tempfile
    s = _settings(tmp_path)
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp))
    (tmp / "old.bin").write_bytes(b"x" * 2**20)
    _old(tmp / "old.bin", 2)
    (tmp / "fresh.bin").write_bytes(b"y")
    (tmp / "link").symlink_to(tmp / "fresh.bin")
    job = s.jobs_dir / "x123" / "hyperopt.fthypt"
    job.parent.mkdir(parents=True)
    job.write_bytes(b"z" * 2**20)
    _old(job, 5)
    candle = s.market_data_dir / "futures" / "BTC_USDT_USDT-1h-futures.feather"
    candle.parent.mkdir(parents=True)
    candle.write_bytes(b"c")
    _old(candle, 5)
    logs = s.user_data / "logs"
    for i in (1, 2, 3, 7):
        (logs / f"freqtrade.log.{i}").write_text("l")
    (logs / "freqtrade.log").write_text("live")
    stale = s.state_dir / ".manifest.json.abc.tmp"
    stale.write_text("{")
    _old(stale, 1)
    reg = Registry(s.registry_path)
    out = storage.janitor_hourly(reg, s)
    assert out["stale_atomic"] == 1 and not stale.exists()
    assert out["tmp"] == {"files": 1, "mb": 1.0} and (tmp / "fresh.bin").exists() and (tmp / "link").is_symlink()
    assert out["leftovers"]["files"] == 2 and not job.exists() and not candle.exists()
    assert s.jobs_dir.is_dir() and s.market_data_dir.is_dir()  # the folders stay
    assert out["logs"] == 2 and (logs / "freqtrade.log").exists() and (logs / "freqtrade.log.2").exists()
    assert reg.kv_get("janitor")["freed_total_mb"] == 2.0
    assert "janitor_freed_mb=2.0" in observe.disk_line(reg)


def test_janitor_never_touches_research_folders_when_research_runs_here(tmp_path):
    s = _settings(tmp_path, mode="local")  # the GitHub lab: research writes these folders right now
    f = s.jobs_dir / "x1" / "result.json"
    f.parent.mkdir(parents=True)
    f.write_text("{}")
    _old(f, 30)
    assert storage.research_leftovers(s) == []
    assert storage.clean_research_leftovers(s)["files"] == 0 and f.exists()


def test_registry_pruning_by_age_and_disk_pressure(tmp_path):
    reg = Registry(tmp_path / "r.db")
    now = utcnow()
    with reg.conn() as c:
        for d in (40, 10, 1):
            c.execute("INSERT INTO events (ts, level, source, message, data) VALUES (?, 'info', 't', 'm', '{}')",
                      (iso(now - timedelta(days=d)),))
    reg.upsert("strategies", {"id": "live", "experiment_id": "e1", "family": "f", "params": {}, "pairs": [],
                              "sides": [], "stage": "exploration", "score": 0, "oos": {}, "gates": {}, "live": {},
                              "created": "", "updated": "", "stage_since": "", "history": []})
    for eid in ("e1", "e2"):
        reg.upsert("experiments", {"id": eid, "created": "", "family": "f", "spec": {}, "status": "done",
                                   "finished": iso(now), "result": {"verdict": "exploratory", "curve": [1, 2, 3]}})
    assert storage.prune_registry(reg, 0.8, now)["events_deleted"] == 1  # 40 days old
    out = storage.prune_registry(reg, 0.15, now)  # low disk: keep a week of events
    assert out["events_deleted"] == 1 and out["candidates_slimmed"] == 0
    out = storage.prune_registry(reg, 0.05, now)  # very low: charts of candidates no live strategy shows
    assert out["candidates_slimmed"] == 1
    res = {r["id"]: r["result"] for r in reg.q("SELECT id, result FROM experiments")}
    assert "curve" in res["e1"] and res["e2"].get("slim") and res["e2"]["verdict"] == "exploratory"


def test_a_working_limit_entry_is_not_a_position_without_stop():
    now = utcnow()
    entry_open = {"ft_order_side": "buy", "ft_is_entry": True, "status": "open", "is_open": True, "filled": 0}
    filled_now = {"ft_order_side": "buy", "ft_is_entry": True, "status": "closed", "is_open": False, "filled": 1,
                  "order_filled_date": iso(now - timedelta(seconds=60))}
    filled_old = filled_now | {"order_filled_date": iso(now - timedelta(minutes=10))}
    trades = [
        {"pair": "A/USDT:USDT", "open_date": iso(now - timedelta(minutes=8)), "orders": [entry_open]},  # waiting
        {"pair": "B/USDT:USDT", "open_date": iso(now - timedelta(minutes=8)), "orders": [filled_now]},  # stop on its way
        {"pair": "C/USDT:USDT", "open_date": iso(now - timedelta(minutes=12)), "orders": [filled_old]},  # bare
        {"pair": "D/USDT:USDT", "open_date": iso(now - timedelta(minutes=20)), "orders": [entry_open]},  # stuck
    ]
    assert observe.health(trades, 50_000, now)["no_exchange_stop"] == ["C/USDT:USDT", "D/USDT:USDT"]


def test_a_partially_filled_entry_without_stop_is_never_hidden():
    """ChatGPT 23.11 (3): ignoring an unfilled order is fine; a filled amount without a stop is not."""
    now = utcnow()
    partial = {"ft_order_side": "sell", "ft_is_entry": True, "status": "open", "is_open": True, "filled": 0.4,
               "order_filled_date": None, "order_date": iso(now - timedelta(minutes=6))}
    young = partial | {"order_date": iso(now - timedelta(seconds=90))}
    trades = [{"pair": "E/USDT:USDT", "open_date": iso(now - timedelta(minutes=6)), "orders": [partial]},
              {"pair": "F/USDT:USDT", "open_date": iso(now - timedelta(seconds=90)), "orders": [young]}]
    assert observe.health(trades, 50_000, now)["no_exchange_stop"] == ["E/USDT:USDT"]

