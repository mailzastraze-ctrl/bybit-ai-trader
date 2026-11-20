"""Deployment self-test: proves the bot is connected to Bybit **Demo** with valid keys.

Results are stored in the registry (kv 'selftest') and shown in the web terminal.
Run manually: python -m aitrader.selftest
"""

from __future__ import annotations

import json
import os
import sys
import time

from aitrader.ftclient import FtClient
from aitrader.registry import Registry
from aitrader.settings import Settings, get_settings
from aitrader.util import iso, parse_dt, utcnow


def run(s: Settings, wait_s: int = 0) -> dict:
    checks: dict[str, dict] = {}

    def check(name: str, ok: bool, detail: object = "") -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}

    cfg = json.loads((s.config_dir / "trade.json").read_text())
    check("config_demo_trading", cfg["exchange"].get("demo_trading") is True and not cfg.get("dry_run"),
          "exchange.demo_trading=true, dry_run=false")

    ft = FtClient(s.ft_api_url, s.ft_api_user, s.ft_api_password)
    deadline = time.time() + wait_s
    while not ft.ping() and time.time() < deadline:
        time.sleep(5)
    up = ft.ping()
    check("bot_api", up, s.ft_api_url)
    if up:
        try:
            sc = ft.show_config()
            check("bot_mode", sc.get("trading_mode") == "futures" and not sc.get("dry_run"),
                  {k: sc.get(k) for k in ("exchange", "trading_mode", "dry_run", "state", "strategy", "version")})
        except Exception as e:  # noqa: BLE001
            check("bot_mode", False, str(e))
        try:
            bal = ft.balance()
            total = float(bal.get("total") or 0)
            bot = float(bal.get("total_bot") or total)
            check("demo_account_auth", total > 0,
                  f"trading capital {bot:.2f} {bal.get('stake', '')} (whole demo account incl. other coins {total:.2f})")
        except Exception as e:  # noqa: BLE001
            check("demo_account_auth", False, str(e))
        try:
            wl = ft.whitelist().get("whitelist", [])
            check("pair_whitelist", len(wl) > 0, wl[:10])
        except Exception as e:  # noqa: BLE001
            check("pair_whitelist", False, str(e))
    logf = s.user_data / "logs" / "freqtrade.log"
    try:
        text = logf.read_text(errors="ignore")[-2_000_000:]
        check("log_demo_enabled", "Demo trading enabled" in text, "freqtrade log confirms Bybit demo endpoint")
    except FileNotFoundError:
        check("log_demo_enabled", False, "no freqtrade log yet")
    result = {"ts": iso(), "ok": all(c["ok"] for c in checks.values()), "checks": checks}
    return result


EXEC_TAG = "exec-test"
EXEC_PAIRS = ["XRP/USDT:USDT", "DOGE/USDT:USDT", "ADA/USDT:USDT", "ETH/USDT:USDT"]


def _find(trades: list[dict], tag: str) -> dict | None:
    for t in trades:
        if t.get("enter_tag") == tag:
            return t
    return None


def _retry(fn, attempts: int = 5, sleep=time.sleep):
    for i in range(attempts):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            if i == attempts - 1:
                raise
            sleep(2)


def cleanup_test_trades(ft: FtClient, sleep=time.sleep) -> list[int]:
    """Close any leftover execution-test positions (e.g. from an interrupted run)."""
    closed = []
    for t in _retry(ft.status, sleep=sleep) or []:
        if (t.get("enter_tag") or "").startswith(EXEC_TAG):
            _retry(lambda tid=t["trade_id"]: ft.forceexit(tid), attempts=2, sleep=sleep)
            closed.append(t["trade_id"])
    return closed


def execution_test(ft: FtClient, stake: float = 30.0, sleep=time.sleep, timeout_s: int = 240) -> dict:
    """End-to-end order test on Bybit Demo: market entry → fill → stop-loss order on the
    exchange → market exit. Proves the full execution path, not just connectivity."""
    steps: dict[str, dict] = {}
    res = {"ts": iso(), "ok": False, "steps": steps}
    leftovers = cleanup_test_trades(ft, sleep=sleep)
    if leftovers:
        steps["cleanup_previous"] = {"ok": True, "detail": {"closed_trade_ids": leftovers}}
        sleep(10)
    tag = f"{EXEC_TAG}-{int(time.time())}"
    try:
        return _execution_test(ft, stake, sleep, timeout_s, steps, res, tag)
    except Exception as e:  # noqa: BLE001 – never leave a test position behind
        steps["error"] = {"ok": False, "detail": str(e)[:300]}
        try:
            cleanup_test_trades(ft, sleep=sleep)
        except Exception:  # noqa: BLE001
            pass
        return res


def _execution_test(ft, stake, sleep, timeout_s, steps, res, tag) -> dict:
    status = lambda: _retry(ft.status, sleep=sleep)  # noqa: E731
    wl = _retry(ft.whitelist, sleep=sleep).get("whitelist", [])
    open_pairs = {t["pair"] for t in status()}
    pair = next((p for p in EXEC_PAIRS if p in wl and p not in open_pairs), None)
    if pair is None:
        steps["pick_pair"] = {"ok": False, "detail": "no free pair for the test"}
        return res
    try:
        ft.forceenter(pair, "long", stake, tag)
        steps["entry_submitted"] = {"ok": True, "detail": {"pair": pair, "stake": stake}}
    except Exception as e:  # noqa: BLE001
        steps["entry_submitted"] = {"ok": False, "detail": str(e)[:300]}
        return res
    trade, deadline = None, time.time() + timeout_s
    while time.time() < deadline:
        trade = _find(status(), tag)
        if trade and not trade.get("has_open_orders") and trade.get("amount"):
            break
        sleep(5)
    if not trade or trade.get("has_open_orders"):
        steps["entry_filled"] = {"ok": False, "detail": "entry not filled in time"}
        return res
    steps["entry_filled"] = {"ok": True, "detail": {"trade_id": trade["trade_id"], "open_rate": trade.get("open_rate"),
                                                    "amount": trade.get("amount"), "leverage": trade.get("leverage")}}
    sl = None
    while time.time() < deadline:
        trade = _find(status(), tag) or trade
        sl = next((o for o in trade.get("orders", []) if o.get("ft_order_side") == "stoploss"
                   and o.get("status") in ("open", "new", None)), None)
        if sl:
            break
        sleep(5)
    steps["stoploss_on_exchange"] = {"ok": sl is not None,
                                     "detail": {"stop_price": (sl or {}).get("stop_price") or trade.get("stop_loss_abs"),
                                                "order_id": (sl or {}).get("order_id")}}
    try:
        ft.forceexit(trade["trade_id"])
    except Exception as e:  # noqa: BLE001
        steps["exit"] = {"ok": False, "detail": str(e)[:300]}
        return res
    closed = None
    while time.time() < deadline + 120:
        if _find(status(), tag) is None:
            closed = next((t for t in _retry(lambda: ft.trades(limit=50), sleep=sleep).get("trades", [])
                           if t.get("enter_tag") == tag), None)
            break
        sleep(5)
    steps["exit"] = {"ok": closed is not None,
                     "detail": {"close_rate": (closed or {}).get("close_rate"),
                                "profit_abs": (closed or {}).get("profit_abs"),
                                "exit_reason": (closed or {}).get("exit_reason")}}
    res["ok"] = all(v["ok"] for k, v in steps.items() if k != "cleanup_previous")
    return res


def run_execution_test_if_due(s: Settings, max_age_days: float = 7.0) -> dict | None:
    reg = Registry(s.registry_path)
    last = reg.kv_get("exec_test") or {}
    ts = parse_dt(last.get("ts"))
    if last.get("ok") and ts and (utcnow() - ts).total_seconds() < max_age_days * 86400:
        return None
    ft = FtClient(s.ft_api_url, s.ft_api_user, s.ft_api_password, timeout=20)
    res = execution_test(ft)
    reg.kv_set("exec_test", res)
    reg.event("selftest", "execution test " + ("PASSED: entry filled, stop-loss on exchange, exit filled"
                                               if res["ok"] else "FAILED: " + json.dumps(res["steps"])[:400]),
              "info" if res["ok"] else "error")
    print(json.dumps(res, indent=2))
    return res


def main() -> int:
    s = get_settings()
    s.ensure_dirs()
    res = run(s, wait_s=int(sys.argv[1]) if len(sys.argv) > 1 else 0)
    reg = Registry(s.registry_path)
    reg.kv_set("selftest", res)
    reg.event("selftest", "self-test " + ("PASSED" if res["ok"] else "FAILED: " + ", ".join(
        k for k, v in res["checks"].items() if not v["ok"])), "info" if res["ok"] else "error")
    print(json.dumps(res, indent=2))
    if res["ok"] and os.environ.get("EXEC_TEST", "1") == "1":
        run_execution_test_if_due(s)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
