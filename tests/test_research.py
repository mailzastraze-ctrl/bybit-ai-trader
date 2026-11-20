import json
import zipfile
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from helpers import make_trades

from aitrader.research import metrics as M
from aitrader.research.generator import ucb_pick
from aitrader.research.results import (
    best_epochs,
    load_backtest,
    load_hyperopt_epochs,
    strategy_stats,
)
from aitrader.research.validation import evaluate_gates, walk_forward_folds
from aitrader.settings import Gates


def test_summarize_and_profit_factor():
    tr = make_trades([50, -20, 30, -10, 40, -25])
    s = M.summarize(tr, 10_000)
    assert s["trades"] == 6
    assert s["profit_factor"] == pytest.approx(120 / 55, rel=1e-3)
    assert s["total_return"] == pytest.approx(0.0065)
    assert 0 < s["max_drawdown"] < 0.01
    assert s["win_rate"] == 0.5


def test_max_drawdown():
    dd = M.max_drawdown_from_pnl(np.array([100, -300, 50, -100]), 1000)
    assert dd == pytest.approx(350 / 1100)  # peak 1100 → trough 750


def test_psr_and_dsr_behaviour():
    assert M.probabilistic_sharpe(0.1, 0.0, 365) > 0.95
    assert M.probabilistic_sharpe(-0.05, 0.0, 365) < 0.2
    # more trials → higher hurdle → lower DSR
    d1 = M.deflated_sharpe(0.08, 365, 1, 1 / 365)
    d50 = M.deflated_sharpe(0.08, 365, 50, 1 / 365)
    assert d1 > d50
    assert abs(M._norm_ppf(0.975) - 1.959964) < 1e-5


def test_monte_carlo():
    good = M.monte_carlo(np.array([20, -10] * 30), 10_000, 500)
    bad = M.monte_carlo(np.array([-20, 10] * 30), 10_000, 500)
    assert good["prob_profit"] > 0.9 > bad["prob_profit"]
    assert 0 <= good["dd_p95"] < 1


def test_robust_loss_prefers_more_trades_and_better_sharpe():
    start, end = datetime(2025, 6, 1, tzinfo=UTC), datetime(2025, 9, 1, tzinfo=UTC)
    few = M.trades_frame(make_trades([10] * 5))
    good = M.trades_frame(make_trades([20, -10] * 40))
    bad = M.trades_frame(make_trades([10, -20] * 40))
    lf, lg, lb = (M.robust_loss(x, 10_000, start, end) for x in (few, good, bad))
    assert lg < lb < lf


def test_walk_forward_folds_tile_holdout():
    folds = walk_forward_folds(datetime(2026, 11, 20, 13, tzinfo=UTC), 300, 120, 2)
    assert len(folds) == 2
    assert folds[0].test_end == folds[1].test_start
    assert folds[1].test_end == datetime(2026, 11, 20, tzinfo=UTC)
    for f in folds:
        assert f.train_end == f.test_start  # train strictly before test
        assert (f.train_end - f.train_start).days == 300
    assert folds[0].test_range == "20260723-20260921"


def _m(trades=40, pf=1.4, sharpe=1.2, dd=0.1, wfe=0.6, spf=1.2, rob=0.8, mc=0.9, dsr=0.9, ret=0.1):
    oos = {"trades": trades, "profit_factor": pf, "sharpe": sharpe, "max_drawdown": dd,
           "total_return": ret}
    return {"oos": oos, "stress": {"profit_factor": spf}, "wfe": wfe, "robust_frac": rob,
            "mc": {"prob_profit": mc}, "dsr": dsr}


def test_gates():
    g = Gates()
    assert evaluate_gates(g, _m())[0] == "validated"
    verdict, gates = evaluate_gates(g, _m(dsr=0.3))
    assert verdict == "exploratory" and not gates["deflated_sharpe"]["pass"]
    assert evaluate_gates(g, _m(trades=5))[0] == "rejected"
    assert evaluate_gates(g, _m(pf=0.9, ret=-0.01))[0] == "rejected"
    # weak "barely positive" results are noise, not exploration material
    assert evaluate_gates(g, _m(pf=1.04, sharpe=0.16, spf=0.97, mc=0.55, dsr=0.01))[0] == "rejected"


def test_ucb_pick():
    assert ucb_pick({"a": (3, 0.5), "b": (0, 0.0)}) == "b"
    assert ucb_pick({"a": (50, 0.9), "b": (50, 0.1)}) == "a"


def test_parse_backtest_zip_and_fthypt(tmp_path):
    # backtest export as written by freqtrade (zip + .last_result.json)
    stats = {"strategy": {"AIPortfolio": {"trades": make_trades([5, -2]), "total_trades": 2}},
             "strategy_comparison": []}
    zname = "backtest-result-2026-11-20_10-00-00.zip"
    with zipfile.ZipFile(tmp_path / zname, "w") as zf:
        zf.writestr(zname.replace(".zip", ".json"), json.dumps(stats))
    (tmp_path / ".last_result.json").write_text(json.dumps({"latest_backtest": zname}))
    st = strategy_stats(load_backtest(tmp_path), "AIPortfolio")
    assert st["total_trades"] == 2 and len(st["trades"]) == 2

    hd = tmp_path / "hyperopt_results"
    hd.mkdir()
    lines = [
        {"loss": 0.5, "params_dict": {"fast": 10}, "results_metrics": {"total_trades": 50, "sharpe": 1.0}},
        {"loss": -1.2, "params_dict": {"fast": 12}, "results_metrics": {"total_trades": 60, "sharpe": 2.0}},
        {"loss": -5.0, "params_dict": {"fast": 14}, "results_metrics": {"total_trades": 3, "sharpe": 9.0}},
    ]
    (hd / "strategy_X.fthypt").write_text("\n".join(json.dumps(x) for x in lines) + "\nNaN-garbage\n")
    (hd / ".last_result.json").write_text(json.dumps({"latest_hyperopt": "strategy_X.fthypt"}))
    eps = load_hyperopt_epochs(hd)
    assert len(eps) == 3
    best = best_epochs(eps, min_trades=20, top=1)[0]
    assert best["params_dict"]["fast"] == 12  # ignores the 3-trade "lucky" epoch


def test_daily_returns_zero_fill():
    df = M.trades_frame(make_trades([10, 10]))
    r = M.daily_returns(df, 1000, pd.Timestamp("2025-05-30", tz="UTC"), pd.Timestamp("2025-06-10", tz="UTC"))
    assert len(r) == 12 and (r >= 0).all()
