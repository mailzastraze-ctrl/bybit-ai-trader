"""Deployment self-test: proves the bot is connected to Bybit **Demo** with valid keys.

Results are stored in the registry (kv 'selftest') and shown in the web terminal.
Run manually: python -m aitrader.selftest
"""

from __future__ import annotations

import json
import sys
import time

from aitrader.ftclient import FtClient
from aitrader.registry import Registry
from aitrader.settings import Settings, get_settings
from aitrader.util import iso


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
            check("demo_account_auth", total > 0, f"account value {total:.2f} {bal.get('stake', '')}")
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


def main() -> int:
    s = get_settings()
    s.ensure_dirs()
    res = run(s, wait_s=int(sys.argv[1]) if len(sys.argv) > 1 else 0)
    reg = Registry(s.registry_path)
    reg.kv_set("selftest", res)
    reg.event("selftest", "self-test " + ("PASSED" if res["ok"] else "FAILED: " + ", ".join(
        k for k, v in res["checks"].items() if not v["ok"])), "info" if res["ok"] else "error")
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
