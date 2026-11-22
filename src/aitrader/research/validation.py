"""Walk-forward windows and promotion gates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from aitrader.settings import Gates


@dataclass(frozen=True)
class Fold:
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime

    @staticmethod
    def _fmt(d: datetime) -> str:
        return d.strftime("%Y%m%d")

    @property
    def train_range(self) -> str:
        return f"{self._fmt(self.train_start)}-{self._fmt(self.train_end)}"

    @property
    def test_range(self) -> str:
        return f"{self._fmt(self.test_start)}-{self._fmt(self.test_end)}"


def walk_forward_folds(end: datetime, train_days: int, holdout_days: int, folds: int) -> list[Fold]:
    """Rolling walk-forward: each fold re-optimises on `train_days` and is tested on the
    next unseen slice. Test slices tile the final `holdout_days` without overlap."""
    end = end.replace(hour=0, minute=0, second=0, microsecond=0)
    step = timedelta(days=holdout_days // folds)
    holdout_start = end - step * folds
    out = []
    for k in range(folds):
        test_start = holdout_start + step * k
        out.append(Fold(test_start - timedelta(days=train_days), test_start, test_start,
                        test_start + step))
    return out


def walk_forward_efficiency(is_annual: float, oos_annual: float) -> float:
    if is_annual <= 0:
        return 0.0
    return oos_annual / is_annual


def score(oos: dict, dsr: float) -> float:
    """Single ranking number (higher is better). Only meaningful for gate-passing strategies."""
    trades = oos.get("trades", 0)
    if trades == 0:
        return 0.0
    sharpe = max(min(oos.get("sharpe", 0.0), 4.0), 0.0)
    dd = min(oos.get("max_drawdown", 1.0), 1.0)
    # steadiness of the unseen-period equity curve (owner's criterion): a jagged curve with the
    # same Sharpe ranks lower; a falling last quarter is a warning sign
    steady = 0.5 + 0.5 * max(min(float(oos.get("curve_r2", 0.0)), 1.0), 0.0)
    recent = 1.0 if float(oos.get("last90_return", 0.0)) >= 0 else 0.7
    return round(sharpe * (1 - dd) * math.sqrt(min(trades, 100) / 100.0) * (0.5 + 0.5 * dsr) * steady * recent, 4)


def clean_oos(spec: dict) -> bool:
    """Are the walk-forward test windows genuinely unseen for this configuration?

    Not for screener survivors: the screener chose them on (almost) the whole history,
    including the last 360 days the walk-forward tests on. Not for external fixed configs
    either (found by hand on the same history). Not for refinements (2026-11-22): the parent
    was picked because of its result on these very windows and its children are searched
    around it and tested on them again – 48 % of refinements passed against 9 % of fresh
    searches. Not for revalidations either: a re-test of a strategy on windows that mostly
    overlap the ones it was chosen on can retire it, not prove it. Fresh searched experiments
    re-optimise on each train window and are tested on the next one, so their test windows
    are clean."""
    return not (spec.get("screen") or spec.get("external") or spec.get("refines") or spec.get("revalidates"))


def evaluate_gates(g: Gates, m: dict) -> tuple[str, dict]:
    """Return ("validated" | "exploratory" | "rejected", per-gate results).

    `m` keys: oos (summary dict), stress (summary), wfe, robust_frac, mc (dict), dsr;
    optional fold_pos, clean_oos (False = test windows were seen when the configuration was chosen),
    alpha/alpha_t (OOS alpha over BTC; only validation needs it, exploration does not).
    """
    oos, stress, mc = m["oos"], m["stress"], m["mc"]
    checks = {
        "trades": (oos["trades"], g.min_trades, oos["trades"] >= g.min_trades),
        "profit_factor": (oos["profit_factor"], g.min_profit_factor,
                          oos["profit_factor"] >= g.min_profit_factor),
        "sharpe": (oos["sharpe"], g.min_sharpe, oos["sharpe"] >= g.min_sharpe),
        "max_drawdown": (oos["max_drawdown"], g.max_drawdown,
                         oos["max_drawdown"] <= g.max_drawdown),
        "wfe": (m["wfe"], g.min_wfe, m["wfe"] >= g.min_wfe),
        "stress_pf": (stress["profit_factor"], g.min_stress_pf,
                      stress["profit_factor"] >= g.min_stress_pf),
        "robustness": (m["robust_frac"], g.min_robust_frac, m["robust_frac"] >= g.min_robust_frac),
        "monte_carlo": (mc["prob_profit"], g.min_mc_prob_profit,
                        mc["prob_profit"] >= g.min_mc_prob_profit),
        "deflated_sharpe": (m["dsr"], g.min_dsr, m["dsr"] >= g.min_dsr),
    }
    fp = m.get("fold_pos")
    if fp is not None:  # every walk-forward slice is its own out-of-sample test
        checks["fold_consistency"] = (fp, g.min_fold_consistency, fp >= g.min_fold_consistency)
    a_t = m.get("alpha_t")
    if a_t is not None:
        # the OOS profit must not be just the market's move (a short book in a falling year)
        ok = a_t >= g.min_alpha_t and (m.get("alpha") or 0.0) > 0
        checks["market_alpha"] = (a_t, g.min_alpha_t, ok)
    if m.get("clean_oos") is False:
        # the configuration was chosen on data that overlaps these test windows (screener
        # survivors, hand-found external configs): the walk-forward is a replication with real
        # fees and funding – it can reject, but it is not out-of-sample evidence, so it can
        # never validate. Only the forward test (data after the freeze) can.
        checks["clean_oos"] = (0.0, 1.0, False)
    gates = {k: {"value": round(float(v), 4), "threshold": t, "pass": bool(ok)}
             for k, (v, t, ok) in checks.items()}
    if all(x["pass"] for x in gates.values()):
        return "validated", gates
    explore_ok = (oos["trades"] >= g.explore_min_trades
                  and oos["profit_factor"] >= g.explore_min_pf
                  and stress["profit_factor"] >= g.explore_min_stress_pf
                  and oos.get("sharpe", 0.0) >= g.explore_min_sharpe
                  and mc.get("prob_profit", 0.0) >= g.explore_min_mc
                  and oos["total_return"] > 0
                  and (fp is None or fp >= g.explore_min_fold_consistency))
    return ("exploratory" if explore_ok else "rejected"), gates
