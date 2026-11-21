"""Stage 1 of the research lab: mass screening with the owner's Strategy Lab engine.

`export_candles` writes the universe's Bybit candles (15m and 1h) as compact JSON for
`screener/screen.js` (Node, the owner's engine.js unchanged), which tries thousands of
strategy × parameter × exit combinations per series and keeps only those that stay
profitable with a steady equity curve on the unseen last 40% of the history.
`to_spec` turns a survivor into a fixed-configuration experiment for the freqtrade
walk-forward (stage 2); the forward test on live data (stage 3) then decides.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path

from aitrader.families import FAMILIES
from aitrader.research.ftrunner import FreqtradeRunner, Job, research_config
from aitrader.settings import Settings
from aitrader.util import utcnow

log = logging.getLogger(__name__)
HISTORY_DAYS = {"1h": 760, "15m": 400}


def series_name(pair: str, tf: str) -> str:
    base = pair
    for ch in ["/", " ", ".", "@", "$", "+", ":"]:
        base = base.replace(ch, "_")
    return f"{base}__{tf}"


def export_candles(s: Settings, pairs: list[str], out: Path, timeframes=("1h", "15m"),
                   ft: FreqtradeRunner | None = None) -> int:
    import pandas as pd
    ft = ft or FreqtradeRunner(s)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for tf in timeframes:
        job = Job(out.parent / f"_dl-{tf}")
        cfg = ft.write_config(job, "config.json", research_config(s, pairs, timeframe=tf))
        start = utcnow() - timedelta(days=HISTORY_DAYS.get(tf, 400))
        try:
            ft.download(job, cfg, pairs, f"{start:%Y%m%d}-", timeframe=tf)
        except Exception as e:  # noqa: BLE001
            log.warning("candle download %s failed: %s", tf, e)
            continue
        for p in pairs:
            f = s.market_data_dir / "futures" / f"{series_name(p, tf).replace('__', '-')}-futures.feather"
            if not f.exists():
                continue
            df = pd.read_feather(f)
            df = df[df["date"] >= pd.Timestamp(start)]
            if len(df) < 2000:
                continue
            (out / f"{series_name(p, tf)}.json").write_text(json.dumps({
                "t": ((df["date"] - pd.Timestamp(0, tz="UTC")) // pd.Timedelta("1ms")).astype("int64").tolist(),
                "o": df["open"].round(8).tolist(), "h": df["high"].round(8).tolist(),
                "l": df["low"].round(8).tolist(), "c": df["close"].round(8).tolist(),
                "v": df["volume"].round(3).tolist()}))
            n += 1
    log.info("exported %d candle series for the screener", n)
    return n


# owner's engine parameter names → the system's twin family parameters
def _map_params(strategy: str, p: dict) -> dict | None:
    g = lambda k, d=0.0: float(p.get(k, d))  # noqa: E731
    m = {
        "zscore": lambda: {"window": g("len"), "z_entry": g("entry"), "z_exit": g("exit")},
        "supertrend": lambda: {"st_len": g("len"), "st_mult": g("mult")},
        "macd": lambda: {"macd_fast": g("fast"), "macd_gap": g("slow") - g("fast"), "macd_signal": g("signal"),
                         "macd_zero": g("zero")},
        "adx_di": lambda: {"di_len": g("len"), "adx_thr": g("thr")},
        "hma_trend": lambda: {"hma_len": g("len")},
        "rsi_revert": lambda: {"rsi_len": g("len"), "rsi_lower": g("lower"), "rsi_exit": g("exitL", 55) - 50,
                               "rsi_trend": g("trend")},
        "stoch": lambda: {"stoch_k": g("k"), "stoch_smooth": g("smooth"), "stoch_d": g("dl"), "stoch_lo": g("lo")},
        "ema_cross": lambda: {"ema_fast": g("fast"), "ema_slow": g("slow"), "ema_trend": g("trend")},
        "bb_revert": lambda: {"br_len": g("len"), "br_mult": g("mult")},
        "donchian": lambda: {"tt_entry": g("entry"), "tt_exit": g("exit")},
    }.get(strategy)
    return m() if m else None


def to_params(sv: dict) -> dict | None:
    fam = FAMILIES.get(sv.get("family", ""))
    entry = _map_params(sv.get("strategy", ""), sv.get("params") or {})
    if fam is None or entry is None:
        return None
    x = sv.get("exits") or {}
    exits = {"sl_atr": float(x.get("sl", 2.0)),
             "tp_rr": float(x["tp"]) if x.get("tp") else 5.0,          # no take-profit ≈ far target
             "trail_rr": 0.5 if x.get("tr") else 3.0,                    # trail from the start, or late
             "trail_atr": float(x["tr"]) if x.get("tr") else 4.0,
             "max_hold": 500, "be_rr": 2.0, "lock_rr": 3.0, "lock_frac": 0.0, "conv_w": 0.0,
             "htf_trend": 0, "vol_regime": 0}
    return fam.normalize({**entry, **exits})


def survivor_id(sv: dict) -> str:
    import hashlib
    key = json.dumps([sv.get("strategy"), sv.get("pairs") or sv.get("pair"), sv.get("timeframe"), sv.get("params"),
                      sv.get("exits")], sort_keys=True)
    return "scr-" + hashlib.sha1(key.encode()).hexdigest()[:10]


def to_specs(screen: dict, job: int = 0, jobs: int = 1, per_job: int = 8, epochs: int = 1) -> list[dict]:
    """Survivors for this runner (round-robin, best first) as fixed-configuration specs."""
    out = []
    for i, sv in enumerate((screen or {}).get("survivors") or []):
        if i % max(jobs, 1) != job:
            continue
        params = to_params(sv)
        if params is None:
            continue
        out.append({"family": sv["family"], "pairs": list(sv.get("pairs") or [sv["pair"]])[:8], "sides": ["long", "short"],
                    "fixed_params": params, "timeframe": sv.get("timeframe") or "1h", "screen": survivor_id(sv),
                    "screen_holdout": {k: sv.get(k) for k in ("B", "r2", "last90", "strategy", "name")},
                    "space_overrides": {}, "used_learnings": [], "epochs": epochs, "seed": 1})
        if len(out) >= per_job:
            break
    return out


def summary(screen: dict, top: int = 30) -> dict:
    sv = (screen or {}).get("survivors") or []
    return {k: screen.get(k) for k in ("created", "evaluated", "series", "seconds", "rules", "engine", "holdout_tests",
                                       "fdr_q", "expected_false", "mode", "tasks")} | {
        "n_survivors": len(sv),
        "top": [{"id": survivor_id(x), **{k: x.get(k) for k in ("name", "family", "pair", "timeframe", "params", "exits",
                                                                 "A", "B", "r2", "last90", "curve", "strategy", "p", "pairs", "pooled")}} for x in sv[:top]]}
