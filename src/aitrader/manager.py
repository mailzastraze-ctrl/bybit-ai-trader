"""Manager loop: watches the bot, syncs trades, records equity, enforces the account
kill-switch, runs the learning loop and the strategy lifecycle, and rewrites the manifest."""

from __future__ import annotations

import time
from datetime import timedelta

from aitrader import context, memguard, readiness, storage
from aitrader.ftclient import FtClient
from aitrader.learner import Learner
from aitrader.lifecycle import Lifecycle
from aitrader.registry import Registry
from aitrader.scanner import Scanner
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
        if (utcnow() - since).total_seconds() > cooldown_h * 3600:
            reg.kv_set("kill_since", None)
            reg.kv_set("equity_peak", equity)  # reset the reference after cooldown
            reg.event("risk", "kill-switch cooldown over – entries resumed", "warning")
            return False
        return True
    if peak > 0 and (peak - equity) / peak >= limit:
        reg.kv_set("kill_since", iso())
        reg.event("risk", f"KILL-SWITCH: equity {equity:.0f} is {(peak - equity) / peak:.1%} below peak "
                  f"{peak:.0f} – new entries paused for {cooldown_h:.0f}h", "error")
        return True
    return False


def daily_stop(reg: Registry, equity: float, limit: float) -> bool:
    """Pause new entries for the rest of the UTC day once equity is `limit` below the day's
    first reading: a bad day stays a bad day. Open positions keep their stops and exits."""
    day = utcnow().strftime("%Y-%m-%d")
    d = reg.kv_get("day_open") or {}
    if d.get("day") != day or not d.get("equity"):
        d = {"day": day, "equity": equity, "hit": False}
        reg.kv_set("day_open", d)
    loss = (d["equity"] - equity) / d["equity"] if d["equity"] else 0.0
    if not d.get("hit"):
        # two consecutive readings (one manager cycle apart): one glitchy balance read must not pause a day
        d["low"] = int(d.get("low", 0)) + 1 if loss >= limit else 0
        d["hit"] = d["low"] >= 2
        reg.kv_set("day_open", d)
    if d.get("hit") and not d.get("announced"):
        d["announced"] = True
        reg.kv_set("day_open", d)
        reg.event("risk", f"DAILY LOSS LIMIT: equity {equity:.0f} is {loss:.1%} below today's first reading "
                  f"{d['equity']:.0f} – new entries paused until 00:00 UTC", "error")
    return bool(d.get("hit"))


def housekeeping(reg: Registry, s=None) -> None:
    """Keep the registry and the volume small: old events/equity rows go, rejected research
    detail is slimmed, rotated logs are trimmed (aitrader.storage), VACUUM weekly or after a
    big slim."""
    now = utcnow()
    last = parse_dt(reg.kv_get("housekeeping_ts"))
    if last and (now - last).total_seconds() < 86400:
        return
    with reg.conn() as c:
        c.execute("DELETE FROM events WHERE ts < ?", (iso(now - timedelta(days=30)),))
        c.execute("DELETE FROM equity WHERE ts < ?", (iso(now - timedelta(days=365))[:16],))
    slimmed = 0
    if s is not None:
        try:  # maintenance must never break the manager loop
            slimmed = storage.maintain(reg, s.data_dir, s.user_data / "logs").get("slimmed", 0)
        except Exception as e:  # noqa: BLE001
            log.warning("storage maintenance failed: %s", e)
    last_vac = parse_dt(reg.kv_get("vacuum_ts"))
    if last_vac is None or (now - last_vac).days >= 7 or slimmed >= 300:
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
    life.import_external(s.app_dir / "research" / "external")
    # make sure the bot has a manifest + pairlist before it starts trading
    life.write(life.build_manifest([], set(scanner.excluded_pairs()), False), [])
    reg.event("manager", "manager started")
    last_learn = last_ready = last_ctx = last_disk = 0.0
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
            paused = kill_switch(reg, equity, s.lifecycle.account_kill_dd,
                                 s.lifecycle.kill_cooldown_hours) if equity > 0 else False
            if equity > 0 and daily_stop(reg, equity, s.lifecycle.daily_loss_limit):
                paused = True
            life.evaluate(equity)
            if time.time() - last_learn > 6 * 3600:
                learner.analyze_live()
                last_learn = time.time()
            if time.time() - last_ctx > 900:  # market context; never blocks trading
                last_ctx = time.time()
                try:
                    before = context.delisted_pairs(reg)
                    context.refresh(reg)
                    new = context.delisted_pairs(reg) - before
                    if new:
                        reg.event("manager", f"Bybit announced delisting of {', '.join(sorted(new))} — no new entries there",
                                  "warning")
                except Exception as e:  # noqa: BLE001
                    log.info("context refresh failed: %s", e)
            # safety: no new entries on coins Bybit has announced to delist (open trades keep their exits)
            excluded = set(scanner.excluded_pairs()) | context.delisted_pairs(reg)
            man = life.build_manifest(open_trades, excluded, paused)
            life.write(man, open_trades)
            detail.update(sleeves=len(man.sleeves), paused=paused)
            if time.time() - last_ready > 600:
                readiness.update(reg, equity if equity > 0 else None)
                last_ready = time.time()
            housekeeping(reg, s)
            if time.time() - last_disk > 900:  # disk usage for the control room (cheap)
                last_disk = time.time()
                try:
                    reg.kv_set("disk", {**(reg.kv_get("disk") or {}), **storage.disk_status(s.data_dir)})
                except OSError:
                    pass
            memguard.release()
            h = memguard.headroom_mb()
            if h is not None:
                detail["mem_headroom_mb"] = round(h)
            reg.heartbeat("manager", "ok" if up else "degraded", detail)
        except Exception as e:  # noqa: BLE001
            log.exception("manager loop error")
            reg.heartbeat("manager", "error", {"error": str(e)[:500], **detail})
        time.sleep(max(5.0, 120 - (time.time() - t0)))


if __name__ == "__main__":
    main()
