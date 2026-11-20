"""Trade-management math shared by research and live strategies (framework independent).

Units: prices in quote currency; `risk` = fraction of equity lost if the stop is hit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd


@dataclass(frozen=True)
class EntryContext:
    entry: float
    atr: float
    is_short: bool

    def sl_distance(self, p: dict) -> float:
        return float(p["sl_atr"]) * self.atr

    def initial_stop(self, p: dict) -> float:
        d = self.sl_distance(p)
        return self.entry + d if self.is_short else self.entry - d

    def take_profit(self, p: dict) -> float:
        d = self.sl_distance(p) * float(p["tp_rr"])
        return self.entry - d if self.is_short else self.entry + d

    def r_multiple(self, price: float, p: dict) -> float:
        d = self.sl_distance(p)
        if d <= 0:
            return 0.0
        move = (self.entry - price) if self.is_short else (price - self.entry)
        return move / d

    def managed_stop(self, p: dict, best_price: float) -> float:
        """Initial stop, moved to break-even and trailed once profit reaches trail_rr·R.

        `best_price` = most favourable price seen since entry (max for long, min for short).
        """
        stop = self.initial_stop(p)
        if self.r_multiple(best_price, p) >= float(p["trail_rr"]):
            trail_dist = float(p["trail_atr"]) * self.atr
            if self.is_short:
                stop = min(stop, self.entry, best_price + trail_dist)
            else:
                stop = max(stop, self.entry, best_price - trail_dist)
        return stop

    def tp_hit(self, price: float, p: dict) -> bool:
        tp = self.take_profit(p)
        return price <= tp if self.is_short else price >= tp


def signal_row(df: pd.DataFrame, open_date: datetime, timeframe_minutes: int) -> pd.Series | None:
    """Return the candle whose close produced the entry signal.

    Works for both live (open_date a few seconds after candle open) and backtesting
    (open_date == candle open): the signal candle is the last candle that *started*
    strictly before the floor of open_date.
    """
    if df is None or df.empty:
        return None
    ts = pd.Timestamp(open_date)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    floor = ts.floor(f"{timeframe_minutes}min")
    dates = df["date"]
    if getattr(dates.dt, "tz", None) is None:
        floor = floor.tz_localize(None)
    sub = df.loc[dates < floor]
    if sub.empty:
        return None
    return sub.iloc[-1]


def bars_held(open_date: datetime, now: datetime, timeframe_minutes: int) -> int:
    return int((now - open_date) / timedelta(minutes=timeframe_minutes))


def size_multiplier(conviction: float, conv_w: float) -> float:
    """Blend constant sizing with conviction-scaled sizing (conviction ∈ [0.5, 1.5])."""
    c = min(max(float(conviction), 0.5), 1.5)
    w = min(max(float(conv_w), 0.0), 1.0)
    return (1.0 - w) + w * c


def stake_for_risk(
    *,
    equity: float,
    risk: float,
    sl_distance_pct: float,
    leverage: float,
    multiplier: float = 1.0,
    min_stake: float | None = None,
    max_stake: float = math.inf,
    max_notional_frac: float = 1.0,
) -> float:
    """Margin (stake) so that hitting the stop loses `risk * multiplier` of equity.

    loss_at_stop = stake * leverage * sl_distance_pct  ⇒  stake = equity*risk / (lev*sl_pct)
    Returns 0 when the trade can't be sized within limits (caller should skip it).
    """
    if equity <= 0 or sl_distance_pct <= 0 or leverage <= 0:
        return 0.0
    stake = equity * risk * multiplier / (leverage * sl_distance_pct)
    stake = min(stake, max_stake, equity * max_notional_frac / leverage)
    if min_stake is not None and stake < min_stake:
        # Bumping to min_stake would exceed the risk budget by >50% → skip trade.
        if min_stake > stake * 1.5:
            return 0.0
        stake = min_stake
    return max(stake, 0.0)
