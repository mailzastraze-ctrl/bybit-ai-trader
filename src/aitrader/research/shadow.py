"""Lab side of the forward test: backtest every frozen strategy on candles after its
freeze time (see aitrader.forward). Runs on GitHub runners, never on the trading server."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from aitrader.manifest import Manifest, Sleeve
from aitrader.realism import real_pnl
from aitrader.research.ftrunner import FreqtradeRunner, Job, research_config
from aitrader.research.results import load_backtest, strategy_stats
from aitrader.settings import Settings
from aitrader.util import parse_dt, utcnow, write_json_atomic

log = logging.getLogger(__name__)
BALANCE = 10_000.0          # research dry-run wallet; returns are reported as a share of it
MIN_FORWARD_H = 6           # nothing to test before a few closed candles exist


def _trades_after(trades: list[dict], freeze) -> list[list]:
    out = []
    for t in trades:
        od, cd = parse_dt(str(t.get("open_date") or "")), str(t.get("close_date") or "")
        if od is None or od < freeze or t.get("exit_reason") == "force_exit":
            continue  # before the freeze (seen in research) or still open at the data end
        out.append([cd[:16], round(real_pnl(t) / BALANCE, 6)])
    return out


def test_one(s: Settings, ft: FreqtradeRunner, root, e: dict) -> dict:
    freeze = parse_dt(e["freeze"])
    base = {k: e.get(k) for k in ("id", "kind", "family", "variant", "score", "freeze", "pairs", "bt_pf", "verdict",
                                  "timeframe", "external")}
    if freeze is None or utcnow() - freeze < timedelta(hours=MIN_FORWARD_H):
        return base | {"ok": True, "trades": []}
    job = Job(root / e["id"])
    try:
        cfg = ft.write_config(job, "config.json", research_config(s, e["pairs"], timeframe=e.get("timeframe"),
                                                                  sides=e.get("sides")))
        man = Manifest(sleeves=[Sleeve(id=f"fw-{e['id']}", family=e["family"], params=e["params"], pairs=e["pairs"],
                                       stage="production", risk=0.01, leverage=s.lifecycle.leverage,
                                       sides=e.get("sides") or ["long", "short"])])
        mpath = job.path("manifest.json")
        write_json_atomic(mpath, man.to_dict())
        overlay = ft.write_config(job, "overlay.json", {"aitrader": {"manifest_path": str(mpath)}})
        out = ft.backtest(job, [cfg, overlay], "AIPortfolio", f"{freeze:%Y%m%d}-", s.research.base_fee, "fw")
        trades = strategy_stats(load_backtest(out), "AIPortfolio").get("trades", [])
        return base | {"ok": True, "trades": _trades_after(trades, freeze)}
    except Exception as ex:  # noqa: BLE001 – one broken strategy must not stop the book
        log.warning("forward test %s failed: %s", e["id"], ex)
        return base | {"ok": False, "error": str(ex)[:300], "trades": []}


def run(s: Settings, entries: list[dict], out, workers: int = 4, ft: FreqtradeRunner | None = None,
        on_progress=None) -> list[dict]:
    ft = ft or FreqtradeRunner(s)
    entries = [e for e in entries if parse_dt(e.get("freeze"))]
    if not entries:
        return []
    root = out / "fw-jobs"
    root.mkdir(parents=True, exist_ok=True)
    for tf in sorted({e.get("timeframe") or s.research.timeframe for e in entries}):
        group = [e for e in entries if (e.get("timeframe") or s.research.timeframe) == tf]
        pairs = sorted({p for e in group for p in e["pairs"]})
        start = min(parse_dt(e["freeze"]) for e in group) - timedelta(days=35)  # + indicator warm-up
        dl = Job(root / f"_download-{tf}")
        cfg = ft.write_config(dl, "config.json", research_config(s, pairs, timeframe=tf))
        ft.download(dl, cfg, pairs, f"{start:%Y%m%d}-", timeframe=tf)
    results, done = [], 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(lambda e: test_one(s, ft, root, e), entries):
            results.append(r)
            done += 1
            if on_progress:
                on_progress(done, len(entries))
    write_json_atomic(out / "shadow-results.json", {"results": results})
    log.info("forward test: %d strategies, %d forward trades, %d errors", len(results),
             sum(len(r["trades"]) for r in results), sum(not r["ok"] for r in results))
    return results
