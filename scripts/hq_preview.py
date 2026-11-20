"""Render the 3D HQ headlessly with realistic demo data and save screenshots.

Used by the hq-preview workflow (GitHub Actions has the CDN + a GPU-less Chromium with
SwiftShader). Fails if the page logs JavaScript errors, so UI regressions are caught.

  python scripts/hq_preview.py --out docs/preview
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT", "LINK/USDT:USDT",
         "ADA/USDT:USDT", "AVAX/USDT:USDT", "SUI/USDT:USDT", "LTC/USDT:USDT"]


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def seed(data: Path) -> None:
    os.environ.update(AITRADER_DATA=str(data), WEB_PASSWORD="pw", AITRADER_PROFILE="lite")
    from aitrader.families import FAMILIES
    from aitrader.manifest import Manifest, Sleeve
    from aitrader.registry import Registry
    from aitrader.settings import get_settings
    s = get_settings()
    s.ensure_dirs()
    reg = Registry(s.registry_path)
    now = datetime.now(timezone.utc)
    rng = random.Random(7)
    eq = 10000.0
    for i in range(400):
        eq *= 1 + rng.gauss(0.0002, 0.002)
        reg.upsert("equity", {"ts": iso(now - timedelta(minutes=10 * (400 - i)))[:15] + "0", "equity": eq, "free": eq * 0.8,
                              "open_trades": 2}, key="ts")
    sleeves = []
    for k, (fam, pairs, stage) in enumerate([("trend_ema", PAIRS[:2], "exploration"), ("meanrev_bb", PAIRS[2:4], "exploration"),
                                             ("trend_ema", PAIRS[4:6], "incubation"), ("squeeze_momentum", PAIRS[6:8], "exploration")]):
        sid = f"b20261120-777-{fam[:5]}-{k:02d}"
        params = FAMILIES[fam].defaults()
        reg.upsert("strategies", {"id": sid, "experiment_id": "", "family": fam, "params": params, "pairs": pairs,
                                  "sides": ["long", "short"], "stage": stage, "score": 0.3 + k * 0.1,
                                  "oos": {"profit_factor": 1.2 + k * 0.1, "sharpe": 0.9 + k * 0.2, "variant": FAMILIES[fam].variant(params)},
                                  "gates": {}, "live": {"trades": 6 + k, "pnl": 12.5 - k * 4, "profit_factor": 1.3 - k * 0.15,
                                                        "win_rate": 0.5}, "created": iso(now), "updated": iso(now),
                                  "stage_since": iso(now), "history": [], "note": "preview"})
        sleeves.append(Sleeve(id=sid, family=fam, params=params, pairs=pairs, stage=stage, risk=0.001, leverage=3,
                              sides=["long", "short"]))
    for st in ("rejected", "rejected", "exploratory", "retired"):
        reg.upsert("strategies", {"id": f"x-{st}-{rng.randrange(999)}", "family": "donchian_breakout", "params": {}, "pairs": [],
                                  "sides": [], "stage": st, "score": 0, "oos": {}, "gates": {}, "live": {}, "created": iso(now),
                                  "updated": iso(now), "stage_since": iso(now), "history": []})
    Manifest(sleeves=sleeves).save(s.manifest_path)
    gates = {"trades": {"pass": True, "value": 64, "threshold": 30}, "profit_factor": {"pass": True, "value": 1.38, "threshold": 1.2},
             "sharpe": {"pass": True, "value": 1.1, "threshold": 0.8}, "max_drawdown": {"pass": True, "value": 0.07, "threshold": 0.2},
             "stress_pf": {"pass": True, "value": 1.12, "threshold": 1.05}, "wfe": {"pass": False, "value": 0.31, "threshold": 0.4},
             "robustness": {"pass": True, "value": 0.75, "threshold": 0.6}, "monte_carlo": {"pass": True, "value": 0.81, "threshold": 0.7},
             "deflated_sharpe": {"pass": False, "value": 0.62, "threshold": 0.9}}
    for j in range(6):
        fam = list(FAMILIES)[j % 4]
        reg.upsert("experiments", {"id": f"x{j:04d}abcdef", "created": iso(now - timedelta(hours=j + 1)), "family": fam,
                                   "spec": {"family": fam, "pairs": PAIRS[:6], "remote": "777"}, "status": "done",
                                   "finished": iso(now - timedelta(hours=j)),
                                   "result": {"verdict": ["exploratory", "rejected"][j % 2], "score": 0.4, "dsr": 0.62, "wfe": 0.31,
                                              "robust_frac": 0.75, "n_trials": 41, "gates": gates, "variant": fam + " +HTF-trend(200)",
                                              "oos": {"trades": 64, "profit_factor": 1.38 - j * 0.1, "sharpe": 1.1 - j * 0.2,
                                                      "max_drawdown": 0.07, "daily_sharpe": 0.05},
                                              "folds": [{"test": "a", "oos": {"trades": 30, "total_return": 0.031, "profit_factor": 1.4}},
                                                        {"test": "b", "oos": {"trades": 34, "total_return": -0.008, "profit_factor": 0.95}}]},
                                   "progress": {"stage": "done"}})
    reg.upsert("experiments", {"id": "xrunning0001", "created": iso(now), "family": "trend_ema",
                               "spec": {"family": "trend_ema", "pairs": PAIRS[:6], "remote": "778", "refines": sleeves[0].id},
                               "status": "running", "started": iso(now),
                               "progress": {"stage": "hyperopt fold 1/2", "epoch": 37, "epochs": 80, "best_loss": -1.8,
                                            "best_trades": 71, "best_profit": 0.124, "budget_left_min": 96, "remote": True}})
    reg.kv_set("lab", {"status": "start", "runs": 3, "cpus": 4, "budget_min": 170, "public": True, "experiments_total": 17,
                       "last_batch": "b20261120-777", "run_id": "778"})
    reg.kv_set("universe", {"ts": iso(now), "pairs": PAIRS, "source": "lab:okx"})
    for p in PAIRS:
        reg.upsert("market", {"pair": p, "ts": iso(now), "data": {"trend_score": rng.random(), "revert_score": rng.random(),
                                                                  "vol_annual": rng.uniform(0.4, 1.4), "ret_30d": rng.uniform(-.2, .2)}},
                   key="pair")
    reg.upsert("learnings", {"id": "L1", "ts": iso(now), "scope": "research", "key": "donchian_breakout",
                             "insight": "donchian_breakout: edge disappears under doubled costs → test longer holds and larger targets",
                             "adjustment": {"space": {"max_hold": [48, 168]}}, "active": 1, "expires": iso(now + timedelta(days=20))})
    for src, msg in [("research", "lab: GitHub research run 778 started (4 CPUs, budget 170 min)"),
                     ("research", "lab: experiment xrunning0001 started — trend_ema on 6 pairs (refines b20261120-777-trend-00)"),
                     ("lifecycle", "manifest v7: 4 sleeves")]:
        reg.event(src, msg)
    reg.heartbeat("manager", "ok", {"mem_headroom_mb": 420})
    reg.heartbeat("research", "busy", {"remote": True})
    reg.kv_set("selftest", {"ok": True})
    reg.kv_set("exec_test", {"ok": True})


class FakeFt:
    """Stands in for the Freqtrade REST API."""

    def __init__(self, *a, **k):
        pass

    def ping(self):
        return True

    def status(self):
        return [{"trade_id": 1, "pair": "BTC/USDT:USDT", "enter_tag": "b20261120-777-trend-00", "is_short": False,
                 "open_rate": 99.0, "stop_loss_abs": 97.0, "initial_stop_loss_abs": 97.0, "profit_abs": 3.2},
                {"trade_id": 2, "pair": "SOL/USDT:USDT", "enter_tag": "b20261120-777-meanr-01", "is_short": True,
                 "open_rate": 101.0, "stop_loss_abs": 103.0, "initial_stop_loss_abs": 103.0, "profit_abs": -1.1}]

    def balance(self):
        return {"total_bot": 10052.3, "stake": "USDT", "currencies": []}

    def profit(self):
        return {"profit_closed_coin": 12.4, "closed_trade_count": 9}

    def daily(self, n):
        return {}

    def health(self):
        return {}

    def show_config(self):
        return {}

    def pair_candles(self, pair, tf, limit):
        rng = random.Random(pair)
        p, rows = 100.0, []
        for i in range(limit):
            o = p
            p *= 1 + rng.gauss(0, 0.006) + 0.002 * math.sin(i / 9)
            rows.append([f"t{i}", o, max(o, p) * 1.003, min(o, p) * 0.997, p, 1000])
        return {"columns": ["date", "open", "high", "low", "close", "volume"], "data": rows}


def serve(port: int):
    import uvicorn

    import aitrader.web.app as webapp
    webapp.FtClient = FakeFt
    webapp.ft = lambda: FakeFt()
    uvicorn.run(webapp.app, host="127.0.0.1", port=port, log_level="warning")


def shoot(port: int, out: Path) -> int:
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        pg = b.new_page(viewport={"width": 1600, "height": 900}, http_credentials={"username": "admin", "password": "pw"})
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f"http://127.0.0.1:{port}/", wait_until="load")
        pg.wait_for_function("window.__hqReady === true", timeout=90_000)
        time.sleep(9)
        pg.screenshot(path=str(out / "hq-overview.png"))
        shots = [("hq-mission", "mission"), ("hq-research", "research"), ("hq-trading", "trading"), ("hq-cloud", "cloud")]
        for name, key in shots:
            label = {"mission": "Company Mission", "research": "Research Lab", "trading": "Trading Floor",
                     "cloud": "GitHub Research Lab"}[key]
            pg.evaluate(f"document.querySelectorAll('.tag').forEach(t => {{ if (t.querySelector('b').textContent.trim() === {json.dumps(label)}) t.click(); }})")
            time.sleep(4)
            pg.screenshot(path=str(out / f"{name}.png"))
        # close-ups: a researcher and a trader (character detail + animation)
        pg.evaluate("document.getElementById('px').click()")
        for name, idx in (("hq-person-research", 3), ("hq-person-trader", 11)):
            pg.evaluate(f"window.__hq.follow({idx})")
            time.sleep(5)
            pg.screenshot(path=str(out / f"{name}.png"))
        b.close()
    (out / "console.txt").write_text("\n".join(errors) or "no errors")
    print("console errors:", errors)
    return len([e for e in errors if "favicon" not in e])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "preview")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    seed(Path(tempfile.mkdtemp()))
    threading.Thread(target=serve, args=(a.port,), daemon=True).start()
    time.sleep(4)
    n = shoot(a.port, a.out)
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
