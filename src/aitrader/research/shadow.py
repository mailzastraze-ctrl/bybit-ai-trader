"""Lab side of the forward test: backtest every frozen strategy on candles after its
freeze time (see aitrader.forward). Runs on GitHub runners, never on the trading server."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from aitrader import tradfi
from aitrader.families import MARKET_PAIR, NEEDS_OI
from aitrader.manifest import Manifest, Sleeve
from aitrader.realism import real_pnl
from aitrader.research.ftrunner import FreqtradeRunner, Job, research_config
from aitrader.research.results import load_backtest, strategy_stats
from aitrader.settings import Settings
from aitrader.util import iso, parse_dt, utcnow, write_json_atomic

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


RESULT_FORMAT = 3  # results carrying it always state their exchange (forward3.accept_source)


def _provenance(s: Settings) -> dict:
    try:
        from freqtrade import __version__ as ftv
    except Exception:  # noqa: BLE001 – unit tests run without freqtrade
        ftv = None
    return {"format": RESULT_FORMAT, "exchange": s.research.exchange, "code_sha": os.environ.get("GITHUB_SHA"),
            "ft_version": ftv}


def _v3(s: Settings, e: dict, trades: list[dict], freeze, now) -> dict | None:
    """Forward v3 record (research/marks.py): value per complete UTC day, open trades marked."""
    from aitrader.research import marks
    from aitrader.research.pipeline import pair_file
    try:
        tf = e.get("timeframe") or s.research.timeframe
        pairs = sorted(set(e.get("pairs") or []) | {t.get("pair") for t in trades if t.get("pair")})
        candles = {p: c for p in pairs if (c := marks.day_candles(pair_file(s, p, tf)))}
        return marks.v3_record(trades, freeze, e.get("pairs") or pairs, candles, tf, now)
    except Exception as ex:  # noqa: BLE001 – the v3 record must never break the v2 forward test
        log.warning("forward v3 record %s failed: %s", e.get("id"), ex)
        return {"error": str(ex)[:200]}  # reported by the server (forward3 status), never silent


def test_one(s: Settings, ft: FreqtradeRunner, root, e: dict) -> dict:
    freeze = parse_dt(e["freeze"])
    base = {k: e.get(k) for k in ("id", "kind", "family", "variant", "score", "freeze", "pairs", "bt_pf", "verdict",
                                  "timeframe", "external", "benchmark", "hypothesis")}
    now = utcnow()
    base["tested_until"] = iso(now)  # data end of this run: the record is observed up to here
    base |= _provenance(s)  # whose candles, which code: only Bybit data counts as forward evidence
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
        fwd = _trades_after(trades, freeze)
        n_open = sum(1 for t in trades if t.get("exit_reason") == "force_exit")
        return base | {"ok": True, "trades": fwd, "v3": _v3(s, e, trades, freeze, now),
                       "diag": {"backtest_trades": len(trades), "still_open": n_open}}
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
        pairs = sorted({p for e in group for p in e["pairs"]} | {MARKET_PAIR})  # BTC: market-relative families
        from aitrader.research.screen import warmup_days
        start = min(parse_dt(e["freeze"]) for e in group) - timedelta(days=warmup_days(tf))  # + indicator warm-up
        dl = Job(root / f"_download-{tf}")
        # TradFi instruments (gold, S&P 500) in their own call: a problem with them must never cost the
        # benchmark, H1 or the research strategies of the same timeframe their candles
        tf_pairs = [p for p in pairs if tradfi.is_tradfi(p)]
        pairs = [p for p in pairs if not tradfi.is_tradfi(p)]
        cfg = ft.write_config(dl, "config.json", research_config(s, pairs, timeframe=tf))
        ft.download(dl, cfg, pairs, f"{start:%Y%m%d}-", timeframe=tf)
        if tf_pairs:
            try:
                tcfg = ft.write_config(dl, "config-tradfi.json", research_config(s, tf_pairs, timeframe=tf))
                ft.download(dl, tcfg, tf_pairs, f"{start:%Y%m%d}-", timeframe=tf)
            except Exception as e:  # noqa: BLE001 – their forward tests then fail alone, visibly
                log.warning("TradFi candles (%s) not downloaded: %s", ", ".join(tf_pairs), str(e)[:200])
        oi_pairs = sorted({p for e in group if e.get("family") in NEEDS_OI for p in e["pairs"]})
        if oi_pairs:
            from aitrader import oi as oimod
            oimod.download(s.market_data_dir, oi_pairs, tf, start, s.research.relay, s.research.relay_token)
    results, done = [], 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(lambda e: test_one(s, ft, root, e), entries):
            results.append(r)
            done += 1
            if on_progress:
                on_progress(done, len(entries))
    write_json_atomic(out / "shadow-results.json", {"results": results})
    log.info("forward test: %d strategies, %d forward trades, %d errors (still open at the data end: %d; "
             "backtest trades since the freeze day: %d)", len(results), sum(len(r["trades"]) for r in results),
             sum(not r["ok"] for r in results), sum((r.get("diag") or {}).get("still_open", 0) for r in results),
             sum((r.get("diag") or {}).get("backtest_trades", 0) for r in results))
    return results
