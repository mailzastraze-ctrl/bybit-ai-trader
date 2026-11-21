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
HISTORY_DAYS = {"1h": 760, "15m": 400, "2h": 1200, "4h": 1200, "6h": 1200, "12h": 1200}
SWING_TIMEFRAMES = ("2h", "4h", "6h", "12h")   # the autopilot: ~3 years + the last 3 months
SWING_TOP = 15                                 # top coins by volume for the autopilot
TF_MIN = {"15m": 15, "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720, "1d": 1440}


def min_bars(tf: str) -> int:
    """Shortest usable series: 2000 bars intraday; ~900 days on the swing timeframes."""
    return int(900 * 1440 / TF_MIN[tf]) if tf in SWING_TIMEFRAMES else 2000


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
            if len(df) < min_bars(tf):
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
    # exactly the engine's exits: ATR stop, optional R take profit, optional chandelier trail
    # from the entry on the current ATR – no break-even, no ratchet, no time exit to speak of
    exits = {"exit_mode": 1, "sl_atr": float(x.get("sl", 2.0)), "lab_tp": float(x.get("tp") or 0.0),
             "lab_trail": float(x.get("tr") or 0.0), "max_hold": 500, "conv_w": 0.0, "htf_trend": 0, "vol_regime": 0}
    return fam.normalize({**entry, **exits})


def survivor_id(sv: dict) -> str:
    import hashlib
    # "x2": configurations are traded with the engine's own exits (exit_mode 1) since 2026-11-21,
    # so everything tested with the earlier approximation gets a fresh walk-forward
    key = json.dumps([sv.get("strategy"), sv.get("pairs") or sv.get("pair"), sv.get("timeframe"), sv.get("params"),
                      sv.get("exits"), "x2"], sort_keys=True)
    return "scr-" + hashlib.sha1(key.encode()).hexdigest()[:10]


def to_specs(screen: dict, job: int = 0, jobs: int = 1, per_job: int = 8, epochs: int = 1,
             skip: set | None = None) -> list[dict]:
    """Survivors for this runner (round-robin, best first) as fixed-configuration specs;
    survivors in `skip` (already walk-forward tested recently) are left out."""
    out = []
    fresh = [sv for sv in (screen or {}).get("survivors") or [] if survivor_id(sv) not in (skip or set())]
    for i, sv in enumerate(fresh):
        if i % max(jobs, 1) != job:
            continue
        params = to_params(sv)
        if params is None:
            continue
        cap = SWING_TOP if sv.get("mode") == "swing" else 8   # an autopilot strategy trades every coin it passed on
        out.append({"family": sv["family"], "pairs": list(sv.get("pairs") or [sv["pair"]])[:cap], "sides": ["long", "short"],
                    "fixed_params": params, "timeframe": sv.get("timeframe") or "1h", "screen": survivor_id(sv),
                    "screen_holdout": {k: sv.get(k) for k in ("B", "r2", "last90", "strategy", "name", "mode", "A", "wf", "mc",
                                                              "robust", "coins", "luck_share")},
                    "space_overrides": {}, "used_learnings": [], "epochs": epochs, "seed": 1})
        if len(out) >= per_job:
            break
    return out


def summary(screen: dict, top: int = 30) -> dict:
    sv = (screen or {}).get("survivors") or []
    return {k: screen.get(k) for k in ("created", "evaluated", "series", "seconds", "rules", "engine", "holdout_tests",
                                       "fdr_q", "expected_false", "mode", "tasks", "swing_tested", "swing_survivors",
                                       "swing_passed_checks", "swing_decoy_survivors", "swing_decoys", "swing_coins_covered")} | {
        "n_survivors": len(sv),
        "top": [{"id": survivor_id(x), **{k: x.get(k) for k in ("name", "family", "pair", "timeframe", "params", "exits",
                                                                 "A", "B", "r2", "last90", "curve", "strategy", "p", "pairs", "pooled",
                                                                 "mode", "wf", "mc", "robust", "coins", "luck_share", "significant",
                                                                 "holdout_from", "wf_from")}} for x in sv[:top]]}


def warmup_days(tf: str, candles: int = 720) -> int:
    """Days of history before a backtest window so `startup_candle_count` candles of `tf`
    exist (the strategies' indicator warm-up); at least the 35 days used for 1h."""
    import math
    return max(35, math.ceil(candles * TF_MIN.get(tf, 60) / 1440) + 5)
