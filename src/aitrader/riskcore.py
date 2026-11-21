"""Trade-management math shared by research and live strategies (framework independent).

Units: prices in quote currency; `risk` = fraction of equity lost if the stop is hit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

BE_FEE_BUFFER = 0.0012  # break-even stop sits ~0.12% beyond entry so fees+slippage are covered
EVENT_LOCK_HOURS = {1: 2.0, 2: 8.0}
VOL_SHOCK_K = {1: 1.6, 2: 2.0, 3: 2.5}


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

    def managed_stop(self, p: dict, best_price: float, now=None, cur_atr: float | None = None) -> float:
        """Active position management (evaluated every few seconds, mirrored to the
        exchange stop). The stop only ever moves in the protective direction:

        1. initial ATR stop;
        2. break-even (+ fee buffer) once the best open profit reached `be_rr`·R;
        3. profit ratchet once it reached `lock_rr`·R: at most (1 − lock_frac) of the best
           open profit can be given back;
        4. ATR trailing once it reached `trail_rr`·R;
        5. optional careful-trader rules (off unless research turned them on):
           * near the take profit (`tp_near` of the way) lock `tp_lock` of the best profit;
           * before a US CPI / jobs / Fed release (`event_lock`) lock half the profit;
           * volatility shock (`vol_shock`: current ATR ≥ k × entry ATR) trail from the best price.

        `best_price` = most favourable price seen since entry (max for long, min for short);
        `now` and `cur_atr` (ATR of the last closed candle) feed the optional rules; backtests
        and live pass the same values, so research measures exactly what trades.
        All thresholds are optimised and validated by research like every other parameter.
        """
        stop = self.initial_stop(p)
        sgn = -1.0 if self.is_short else 1.0
        d = self.sl_distance(p)
        r_best = self.r_multiple(best_price, p)

        def tighten(level: float) -> None:
            nonlocal stop
            stop = min(stop, level) if self.is_short else max(stop, level)

        be = p.get("be_rr")
        if be is not None and r_best >= float(be):
            buffer = min(BE_FEE_BUFFER * self.entry, 0.5 * float(be) * d)  # cover fees, stay below best
            tighten(self.entry + sgn * buffer)
        lock_rr, lock_frac = p.get("lock_rr"), p.get("lock_frac")
        if lock_rr is not None and lock_frac is not None and r_best >= float(lock_rr):
            tighten(self.entry + sgn * float(lock_frac) * abs(best_price - self.entry))
        if r_best >= float(p["trail_rr"]):
            trail_dist = float(p["trail_atr"]) * self.atr
            tighten(self.entry)
            tighten(best_price - sgn * trail_dist)
        gain = abs(best_price - self.entry) if r_best > 0 else 0.0
        tp_near = float(p.get("tp_near") or 0.0)
        if tp_near > 0 and r_best >= tp_near * float(p["tp_rr"]):
            tighten(self.entry + sgn * float(p.get("tp_lock", 0.75)) * gain)
        ev = int(p.get("event_lock") or 0)
        if ev and now is not None and r_best >= 0.5:
            from aitrader.context import hours_to_next_event
            h = hours_to_next_event(now)
            if h is not None and h <= EVENT_LOCK_HOURS.get(ev, 0):
                tighten(self.entry + sgn * 0.5 * gain)
        vs = int(p.get("vol_shock") or 0)
        if vs and cur_atr and r_best >= 0.5 and cur_atr >= VOL_SHOCK_K.get(vs, 99) * self.atr:
            tighten(best_price - sgn * float(p["trail_atr"]) * self.atr)
        return stop

    def break_even(self) -> float:
        """Entry plus a fee buffer in the profitable direction."""
        b = BE_FEE_BUFFER * self.entry
        return self.entry - b if self.is_short else self.entry + b

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
