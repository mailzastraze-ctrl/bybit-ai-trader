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
