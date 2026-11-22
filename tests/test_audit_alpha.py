"""Audit 2026-11-22, B7: a missing alpha over BTC (no BTC candles, too few days) must not pass
as a successful alpha check. `validated` needs the alpha; exploration does not."""

from pathlib import Path

import pytest

from aitrader.registry import Registry
from aitrader.research.validation import evaluate_gates
from aitrader.settings import Gates, Settings


@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=tmp_path, app_dir=Path(__file__).resolve().parents[1])
    s.ensure_dirs()
    return s, Registry(s.registry_path)


def _metrics(**kw):
    oos = {"trades": 500, "profit_factor": 3.0, "sharpe": 3.0, "max_drawdown": 0.05, "total_return": 0.5}
    m = {"oos": oos, "stress": {"profit_factor": 2.5}, "wfe": 1.0, "robust_frac": 1.0, "mc": {"prob_profit": 1.0},
         "dsr": 0.99, "fold_pos": 1.0, "clean_oos": True}
    m.update(kw)
    return m


def test_missing_alpha_never_validates():
    verdict, gates = evaluate_gates(Gates(), _metrics(alpha=None, alpha_t=None))
    assert verdict == "exploratory"  # still tradable at tiny risk; only the strict verdict needs the alpha
    assert gates["market_alpha"]["pass"] is False


def test_alpha_present_decides_as_before():
    assert evaluate_gates(Gates(), _metrics(alpha=0.01, alpha_t=3.0))[0] == "validated"
    assert evaluate_gates(Gates(), _metrics(alpha=-0.01, alpha_t=3.0))[0] == "exploratory"
    assert evaluate_gates(Gates(), _metrics(alpha=0.01, alpha_t=0.5))[0] == "exploratory"


def test_market_split_reads_btc_at_the_experiment_timeframe(env):
    """BTC is now downloaded with every experiment at its own timeframe; the split must find it
    there and not only at the base timeframe (which might be missing or stale)."""
    import numpy as np
    import pandas as pd
    pytest.importorskip("pyarrow")
    from aitrader.families import MARKET_PAIR
    from aitrader.research.pipeline import Pipeline, pair_file
    s, reg = env
    fn = pair_file(s, MARKET_PAIR, "4h")
    assert not pair_file(s, MARKET_PAIR).exists()  # nothing at the base timeframe
    fn.parent.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range("2025-01-01", periods=6 * 120, freq="4h", tz="UTC")
    px = 50_000 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.01, len(idx))))
    pd.DataFrame({"date": idx, "open": px, "high": px, "low": px, "close": px, "volume": 1.0}).to_feather(fn)
    trades = [{"close_date": (idx[0] + pd.Timedelta(days=d, hours=12)).isoformat(), "profit_abs": 5.0 + (d % 3)}
              for d in range(110)]
    pipe = Pipeline(s, reg, runner=object())
    assert pipe._oos_market_split(trades, idx[0], idx[-1]) is None  # base timeframe only: not measurable
    m = pipe._oos_market_split(trades, idx[0], idx[-1], tf="4h")
    assert m is not None and m["days"] >= 30
