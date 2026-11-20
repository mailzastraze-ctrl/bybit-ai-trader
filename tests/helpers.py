import numpy as np
import pandas as pd


def ohlcv(n: int = 2000, seed: int = 1, drift: float = 0.0, vol: float = 0.01,
          start: str = "2025-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # regime-switching returns so every family gets signals
    regime = np.sin(np.arange(n) / 150.0)
    rets = rng.normal(drift + 0.0015 * regime, vol, n)
    close = 100 * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[close[0]], close[:-1]])
    spread = np.abs(rng.normal(0, vol / 2, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.lognormal(10, 0.5, n)
    dates = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low,
                         "close": close, "volume": volume})


def make_trades(pnls, start="2025-06-01", pair="BTC/USDT:USDT", tag="s1", hours=7):
    out = []
    t0 = pd.Timestamp(start, tz="UTC")
    for i, p in enumerate(pnls):
        od = t0 + pd.Timedelta(hours=hours * i)
        cd = od + pd.Timedelta(hours=hours - 1)
        out.append({"trade_id": i + 1, "pair": pair, "open_date": od.isoformat(),
                    "close_date": cd.isoformat(), "profit_abs": float(p),
                    "profit_ratio": float(p) / 1000.0, "exit_reason": "take_profit" if p > 0 else "stop_loss",
                    "enter_tag": tag, "is_short": bool(i % 2), "open_rate": 100.0, "close_rate": 100 + p,
                    "max_rate": 103.0, "min_rate": 97.0, "initial_stop_loss_abs": 98.0,
                    "leverage": 3.0, "stake_amount": 100.0, "is_open": False})
    return out
