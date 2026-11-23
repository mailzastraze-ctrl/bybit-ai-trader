"""Market scanner: selects the liquid Bybit USDT-perp universe (via Freqtrade's
VolumePairList/AgeFilter/SpreadFilter), keeps its history downloaded, and scores every
pair for trend-following vs mean-reversion affinity."""

from __future__ import annotations

import logging
from datetime import timedelta

import numpy as np
import pandas as pd

from aitrader import indicators as ta
from aitrader import tradfi
from aitrader.registry import Registry
from aitrader.research.ftrunner import (
    FreqtradeError,
    FreqtradeRunner,
    Job,
    research_config,
    scan_config,
)
from aitrader.research.pipeline import pair_file, pairs_with_history
from aitrader.settings import Settings
from aitrader.util import iso, utcnow

log = logging.getLogger(__name__)

FALLBACK_UNIVERSE = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT",
    "BNB/USDT:USDT", "ADA/USDT:USDT", "LINK/USDT:USDT", "AVAX/USDT:USDT", "LTC/USDT:USDT",
    "DOT/USDT:USDT", "BCH/USDT:USDT", "TRX/USDT:USDT", "NEAR/USDT:USDT", "SUI/USDT:USDT",
    "APT/USDT:USDT", "ARB/USDT:USDT", "OP/USDT:USDT", "ATOM/USDT:USDT", "FIL/USDT:USDT",
    "ETC/USDT:USDT", "UNI/USDT:USDT", "AAVE/USDT:USDT", "INJ/USDT:USDT",
]


def pair_scores(df: pd.DataFrame) -> dict:
    """Regime/affinity metrics from the last ~60 days of hourly candles."""
    df = df.tail(24 * 60).reset_index(drop=True)
    if len(df) < 24 * 20:
        return {}
    ret = np.log(df["close"]).diff().dropna()
    er = ta.efficiency_ratio(df["close"], 24).mean()
    adx = ta.adx(df, 14)["adx"].mean()
    ac1 = ret.autocorr(1)
    vol_ann = ret.std() * np.sqrt(24 * 365)
    trend = float(np.nan_to_num(er) * 0.6 + np.nan_to_num(adx) / 50.0 * 0.4)
    revert = float((1 - np.nan_to_num(er)) * 0.6 + max(0.0, -np.nan_to_num(ac1)) * 4 * 0.4)
    notional = float((df["close"] * df["volume"]).tail(24 * 7).mean() * 24)
    return {
        "trend_score": round(trend, 4),
        "revert_score": round(revert, 4),
        "efficiency": round(float(np.nan_to_num(er)), 4),
        "adx": round(float(np.nan_to_num(adx)), 2),
        "autocorr1": round(float(np.nan_to_num(ac1)), 4),
        "vol_annual": round(float(vol_ann), 4),
        "ret_30d": round(float(df["close"].iloc[-1] / df["close"].iloc[-24 * 30] - 1), 4),
        "turnover_24h_est": round(notional, 0),
    }


def holdout_start(holdout_days: int, now=None):
    """First day of the walk-forward test windows (`validation.walk_forward_folds`). Regime
    scores used to choose research pairs must be measured before it: the last ~60 days lie
    inside the last test window, so choosing pairs on them lets the test result leak into the
    choice of coins (review 2026-11-22)."""
    end = (now or utcnow()).replace(hour=0, minute=0, second=0, microsecond=0)
    return end - timedelta(days=holdout_days)


class Scanner:
    def __init__(self, settings: Settings, registry: Registry, runner: FreqtradeRunner | None = None):
        self.s = settings
        self.reg = registry
        self.ft = runner or FreqtradeRunner(settings)

    def refresh(self) -> list[str]:
        job = Job(self.s.jobs_dir / "_scan")
        cfg = self.ft.write_config(job, "scan.json", scan_config(self.s))
        try:
            liquid = self.ft.test_pairlist(job, cfg)
            source = "VolumePairList"
        except (FreqtradeError, Exception) as e:  # noqa: BLE001
            log.warning("pairlist scan failed (%s) – using fallback universe", e)
            self.reg.event("scanner", f"pairlist scan failed, fallback universe: {e}"[:400], "warning")
            liquid, source = list(FALLBACK_UNIVERSE), "fallback"
        excluded = set(self.excluded_pairs())
        # gold / S&P 500 perpetuals are high-volume too, but they are the TradFi lane's universe
        # (`tradfi_universe`), never crypto research pairs
        liquid = [p for p in liquid if p.endswith(":USDT") and p not in excluded and not tradfi.is_tradfi(p)]
        liquid = liquid[: self.s.research.universe_size]

        rs = self.s.research
        start = utcnow() - timedelta(days=rs.train_days + rs.holdout_days + 45)
        dl_cfg = self.ft.write_config(job, "download.json", research_config(self.s, liquid))
        try:
            self.ft.download(job, dl_cfg, liquid, f"{start:%Y%m%d}-")
        except FreqtradeError as e:
            self.reg.event("scanner", f"download failed: {e}"[:400], "error")
        universe = pairs_with_history(self.s, liquid, rs.min_history_days)
        log.info("scan: %d liquid pairs (%s), %d with >= %d days of data", len(liquid), source,
                 len(universe), rs.min_history_days)

        now = iso()
        oos_start = holdout_start(rs.holdout_days)
        for p in universe:
            try:
                df = pd.read_feather(pair_file(self.s, p))
                sc = pair_scores(df)
                if sc:
                    pre = pair_scores(df[df["date"] < pd.Timestamp(oos_start)])
                    if pre:
                        sc["pre_oos"] = {**pre, "until": iso(oos_start)}
            except Exception as e:  # noqa: BLE001
                log.warning("scoring %s failed: %s", p, e)
                continue
            if sc:
                self.reg.upsert("market", {"pair": p, "ts": now, "data": sc}, key="pair")
        self.reg.kv_set("universe", {"ts": now, "pairs": universe, "source": source})
        self.reg.event("scanner", f"universe refreshed: {len(universe)} pairs ({source})")
        return universe

    def tradfi_universe(self) -> dict:
        """The independent TradFi universe (gold, S&P 500): fixed instruments, not ranked by volume.
        Which of them the demo account can trade, whether their market is open and how they
        move with BTC comes from the live bot (`tradfi.refresh`, every 15 minutes)."""
        st = self.reg.kv_get(tradfi.K_STATE) or {}
        av = st.get("available") or {}
        return {"pairs": [p for p in tradfi.TRADFI_PAIRS if av.get(p) is not False],
                "instruments": {p: {**v, "available": av.get(p), "open_now": (st.get("open_now") or {}).get(p),
                                    "corr_btc": ((st.get("corr") or {}).get("vs_btc") or {}).get(p)}
                                for p, v in tradfi.INSTRUMENTS.items()},
                "not_tradfi": dict(tradfi.NOT_TRADFI), "ts": st.get("ts")}

    def excluded_pairs(self) -> list[str]:
        rows = self.reg.q("SELECT adjustment, expires FROM learnings WHERE active=1 AND scope='pair'")
        now = iso()
        return [r["adjustment"].get("exclude_pair") for r in rows
                if isinstance(r.get("adjustment"), dict) and r["adjustment"].get("exclude_pair")
                and (not r.get("expires") or r["expires"] > now)]
