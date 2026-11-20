"""Demo → reality adjustment.

Bybit Demo fills never touch the real order book, so they show no slippage and no market
impact. Every demo result the system *decides* on (promotion, retirement, readiness) is
therefore haircut by a conservative per-side slippage on the traded notional.
"""

from __future__ import annotations

import os

SLIPPAGE_PER_SIDE = float(os.environ.get("REALISM_SLIPPAGE", "0.0005"))  # 5 bp per fill


def trade_cost(t: dict, slip: float = SLIPPAGE_PER_SIDE) -> float:
    """Extra cost (quote currency) a real fill would likely have paid: entry + exit."""
    try:
        stake = float(t.get("stake_amount") or 0.0)
        lev = float(t.get("leverage") or 1.0)
    except (TypeError, ValueError):
        return 0.0
    return max(stake * lev, 0.0) * slip * 2


def real_pnl(t: dict, slip: float = SLIPPAGE_PER_SIDE) -> float:
    return float(t.get("profit_abs") or 0.0) - trade_cost(t, slip)


def real_ratio(t: dict, slip: float = SLIPPAGE_PER_SIDE) -> float:
    """Return on stake after the haircut (comparable to freqtrade's profit_ratio)."""
    stake = float(t.get("stake_amount") or 0.0)
    r = float(t.get("profit_ratio") or 0.0)
    if stake <= 0:
        return r
    return r - trade_cost(t, slip) / stake
