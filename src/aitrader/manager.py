"""Manager loop: watches the bot, syncs trades, records equity, enforces the account
kill-switch, runs the learning loop and the strategy lifecycle, and rewrites the manifest."""

from __future__ import annotations

import time
from datetime import timedelta
from sqlite3 import Error as SQLiteError

from aitrader import memguard, readiness
from aitrader.backup import backup_databases
from aitrader.ftclient import FtClient
from aitrader.learner import Learner
from aitrader.lifecycle import Lifecycle
from aitrader.manifest import Manifest
from aitrader.registry import Registry
from aitrader.scanner import Scanner
from aitrader.selftest import execution_verified
from aitrader.settings import get_settings
from aitrader.util import iso, parse_dt, setup_logging, utcnow

log = setup_logging("manager")


def bot_equity(bal: dict) -> tuple[float, float]:
    total = float(bal.get("total_bot") or bal.get("total") or 0.0)
    free = 0.0
    for c in bal.get("currencies", []):
        if c.get("currency") == bal.get("stake", "USDT"):
            free = float(c.get("free") or 0.0)
    return total, free


def kill_switch(reg: Registry, equity: float, limit: float, cooldown_h: float) -> bool:
    """Pause new entries when equity is `limit` below its peak; resume after cooldown."""
    peak = float(reg.kv_get("equity_peak", 0.0) or 0.0)
    if equity > peak:
        reg.kv_set("equity_peak", equity)
        peak = equity
    since = parse_dt(reg.kv_get("kill_since"))
    if since is not None:
        recovered = peak > 0 and equity > 0 and (peak - equity) / peak < limit
        if recovered and (utcnow() - since).total_seconds() > cooldown_h * 3600:
            reg.kv_set("kill_since", None)
            reg.event("risk", "equity recovered and kill-switch cooldown elapsed", "warning")
            return False
        return True
    if peak > 0 and (peak - equity) / peak >= limit:
        reg.kv_set("kill_since", iso())
        reg.event("risk", f"KILL-SWITCH: equity {equity:.0f} is {(peak - equity) / peak:.1%} below peak "
                  f"{peak:.0f} – new entries paused for {cooldown_h:.0f}h", "error")
        return True
    return False


def housekeeping(reg: Registry) -> None:
    """Keep the registry small: old events/equity rows go, VACUUM weekly."""
    now = utcnow()
    last = parse_dt(reg.kv_get("housekeeping_ts"))
    if last and (now - last).total_seconds() < 86400:
        return
    with reg.conn() as c:
        c.execute("DELETE FROM events WHERE ts < ?", (iso(now - timedelta(days=30)),))
        c.execute("DELETE FROM equity WHERE ts < ?", (iso(now - timedelta(days=365))[:16],))
    last_vac = parse_dt(reg.kv_get("vacuum_ts"))
    if last_vac is None or (now - last_vac).days >= 7:
        with reg.conn() as c:
            c.execute("VACUUM")
        reg.kv_set("vacuum_ts", iso(now))
    reg.kv_set("housekeeping_ts", iso(now))


def main() -> None:
    s = get_settings()
    s.ensure_dirs()
    reg = Registry(s.registry_path)
    ft = FtClient(s.ft_api_url, s.ft_api_user, s.ft_api_password)
    life, learner, scanner = Lifecycle(s, reg), Learner(s, reg), Scanner(s, reg)
    life.bootstrap()
    life.import_offline_candidates(s.app_dir / "research" / "imports")
    # make sure the bot has a manifest + pairlist before it starts trading
    if not s.manifest_path.exists():
        life.write(life.build_manifest([], set(scanner.excluded_pairs()), True), [])
    reg.event("manager", "manager started")
    last_learn = last_ready = last_backup = 0.0
    while True:
        t0 = time.time()
        detail: dict = {}
        try:
            up = ft.ping()
            detail["bot"] = "up" if up else "down"
            open_trades: list[dict] = []
            equity = float(reg.kv_get("last_equity", 0.0) or 0.0)
            if up:
                open_trades = ft.status()
                equity, free = bot_equity(ft.balance())
                reg.kv_set("last_equity", equity)
                reg.upsert("equity", {"ts": iso()[:15] + "0", "equity": equity, "free": free,
                                      "open_trades": len(open_trades)}, key="ts")
                learner.sync_trades(ft.all_closed_trades())
                detail.update(equity=round(equity, 2), open_trades=len(open_trades))
            verified = execution_verified(reg)
            killed = kill_switch(reg, equity, s.lifecycle.account_kill_dd,
                                 s.lifecycle.kill_cooldown_hours) if up else True
            paused = not up or equity <= 0 or killed or not verified
            detail["execution_verified"] = verified
            if verified and up and equity > 0:
                life.evaluate(equity)
            if time.time() - last_learn > 6 * 3600:
                learner.analyze_live()
                last_learn = time.time()
            man = life.build_manifest(open_trades, set(scanner.excluded_pairs()), paused)
            life.write(man, open_trades)
            detail.update(sleeves=len(man.sleeves), paused=paused)
            if time.time() - last_ready > 600:
                readiness.update(reg, equity if equity > 0 else None)
                last_ready = time.time()
            housekeeping(reg)
            if time.time() - last_backup > 3600:
                last_backup = time.time()
                try:
                    saved = backup_databases(s.state_dir)
                    reg.kv_set("backup", {"ts": iso(), "files": saved})
                    reg.heartbeat("backup", "ok", saved)
                except (OSError, SQLiteError) as e:
                    reg.heartbeat("backup", "error", {"error": type(e).__name__})
                    log.warning("SQLite backup failed: %s", type(e).__name__)
            memguard.release()
            h = memguard.headroom_mb()
            if h is not None:
                detail["mem_headroom_mb"] = round(h)
            reg.heartbeat("manager", "ok" if up else "degraded", detail)
        except Exception as e:  # noqa: BLE001
            log.exception("manager loop error")
            manifest = Manifest.load(s.manifest_path)
            if not manifest.entries_paused:
                manifest.entries_paused = True
                manifest.save(s.manifest_path)
            reg.heartbeat("manager", "error", {"error": str(e)[:500], **detail})
        time.sleep(max(5.0, 120 - (time.time() - t0)))


if __name__ == "__main__":
    main()
