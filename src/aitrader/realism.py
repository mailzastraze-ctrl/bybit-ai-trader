"""Demo → reality adjustment.

Bybit Demo fills never touch the real order book, so they show no slippage and no market
impact. Every demo result the system *decides* on (promotion, retirement, readiness) is
therefore haircut by a conservative per-side slippage on the traded notional.
"""

from __future__ import annotations

SLIPPAGE_PER_SIDE = 0.0005


def trade_cost(t: dict, slip: float = SLIPPAGE_PER_SIDE) -> float:
    """Extra cost (quote currency) a real fill would likely have paid: entry + exit."""
    raw = t.get("raw") or t
    executed = []
    for order in raw.get("orders") or []:
        amount = float(order.get("filled") or 0)
        price = float(order.get("average") or order.get("safe_price") or order.get("price") or 0)
        if amount > 0 and price > 0:
            executed.append((order.get("ft_order_side"), amount * price))
    sides = {side for side, _ in executed if side in {"buy", "sell", "stoploss"}}
    entry_side = "sell" if t.get("is_short") else "buy"
    if entry_side in sides and sides - {entry_side}:
        return slip * sum(notional for _, notional in executed)
    try:
        stake = float(t.get("stake_amount") or 0.0)
        lev = float(t.get("leverage") or 1.0)
        opened = float(t.get("open_rate") or 0.0)
        closed = float(t.get("close_rate") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    exit_scale = closed / opened if opened > 0 and closed > 0 else 1.0
    return max(stake * lev, 0.0) * slip * (1 + exit_scale)


def real_pnl(t: dict, slip: float = SLIPPAGE_PER_SIDE) -> float:
    return float(t.get("profit_abs") or 0.0) - trade_cost(t, slip)


def real_ratio(t: dict, slip: float = SLIPPAGE_PER_SIDE) -> float:
    """Return on stake after the haircut (comparable to freqtrade's profit_ratio)."""
    stake = float(t.get("stake_amount") or 0.0)
    r = float(t.get("profit_ratio") or 0.0)
    if stake <= 0:
        return r
    return r - trade_cost(t, slip) / stake
