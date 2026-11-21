"""Decides what to research next.

* Family choice: UCB1 bandit over past experiment scores (exploit what works, keep
  exploring the rest).
* Universe: pairs ranked by the family's market-regime affinity from the scanner.
* Learnings: active search-space adjustments are applied to ~half of the experiments so
  their effect can be measured against unmodified runs (A/B), and pruned if useless.
"""

from __future__ import annotations

import math
import random

from aitrader.families import FAMILIES, MULTI_TF
from aitrader.families.base import CONTEXT_GENES, EXIT_GENES, LAB_EXIT
from aitrader.registry import Registry
from aitrader.settings import Settings
from aitrader.util import iso

HIGHER_TF = {"tsmom": ("4h", 0.5)}  # family → (timeframe, share of its new experiments)


def ucb_pick(stats: dict[str, tuple[int, float]], c: float = 0.6, rng: random.Random | None = None) -> str:
    """stats: family -> (n_experiments, mean_reward). Untried families first."""
    rng = rng or random.Random()
    untried = [f for f, (n, _) in stats.items() if n == 0]
    if untried:
        return rng.choice(untried)
    total = sum(n for n, _ in stats.values())
    return max(stats, key=lambda f: stats[f][1] + c * math.sqrt(math.log(total) / stats[f][0]))


def ucb_rank(stats: dict[str, tuple[int, float]], c: float = 0.6) -> list[str]:
    """Families ordered by UCB score (untried first) – parallel jobs start on different ones."""
    total = max(sum(n for n, _ in stats.values()), 1)

    def score(f):
        n, m = stats[f]
        return float("inf") if n == 0 else m + c * math.sqrt(math.log(max(total, 2)) / n)
    return sorted(stats, key=score, reverse=True)


class Generator:
    def __init__(self, settings: Settings, registry: Registry, seed: int | None = None,
                 stats_override: dict | None = None):
        self.s = settings
        self.reg = registry
        self.rng = random.Random(seed)
        # research lab: the bandit uses the live server's full experiment history
        self.stats_override = stats_override

    def family_stats(self) -> dict[str, tuple[int, float]]:
        """(n, mean reward) per family: the live server's history (research lab) plus the
        experiments finished locally in this run, so a run doesn't repeat one family."""
        stats = {f: (0, 0.0) for f in FAMILIES}
        for f, v in (self.stats_override or {}).items():
            if f in stats and isinstance(v, (list, tuple)) and len(v) == 2:
                stats[f] = (int(v[0]), float(v[1]))
        # Only completed experiments are evidence about a family. Infrastructure failures (data,
        # memory, a broken run) say nothing about the strategy and must not steer the bandit.
        rows = self.reg.q("SELECT family, result, status FROM experiments WHERE status='done'")
        acc: dict[str, list[float]] = {f: [] for f in FAMILIES}
        for r in rows:
            if r["family"] not in acc:
                continue
            res = r.get("result") if isinstance(r.get("result"), dict) else {}
            reward = res.get("score", 0.0) if res.get("verdict") in ("validated", "exploratory") else 0.0
            acc[r["family"]].append(float(reward))
        for f, xs in acc.items():
            if xs:
                n0, m0 = stats[f]
                stats[f] = (n0 + len(xs), (n0 * m0 + sum(xs)) / (n0 + len(xs)))
        return stats

    def active_learnings(self, family: str) -> list[dict]:
        now = iso()
        rows = self.reg.q("SELECT * FROM learnings WHERE active=1 AND scope IN ('family','research') AND key=?",
                          (family,))
        return [r for r in rows if not r.get("expires") or r["expires"] > now]

    def revalidation_spec(self, universe: list[str], every_days: int = 14) -> dict | None:
        """Live strategies drift: periodically re-run walk-forward research for each
        production/incubation strategy on its pairs with fresh data."""
        from aitrader.util import parse_dt, utcnow
        now = utcnow()
        for st in self.reg.q("SELECT id, family, pairs, stage_since, oos FROM strategies "
                             "WHERE stage IN ('production','incubation','eligible') ORDER BY score DESC"):
            since = parse_dt(st.get("stage_since"))
            last = parse_dt((self.reg.kv_get("revalidated") or {}).get(st["id"]))
            ref = last or since
            if ref is None or (now - ref).days < every_days:
                continue
            spec = self.next_spec(universe, family=st["family"])
            own = [p for p in (st.get("pairs") or []) if p in universe]
            spec["pairs"] = (own + [p for p in spec["pairs"] if p not in own])[: max(len(own), self.s.research.pairs_per_experiment)]
            spec["revalidates"] = st["id"]
            spec["timeframe"] = (st.get("oos") or {}).get("timeframe") or "1h"  # re-test on its own candles
            marks = self.reg.kv_get("revalidated") or {}
            marks[st["id"]] = iso()
            self.reg.kv_set("revalidated", marks)
            return spec
        return None

    def refine_spec(self, universe: list[str], cand: dict, width: float = 0.2) -> dict:
        """Exploit: re-search a narrowed space (±width of each range) around a promising
        candidate's parameters, on its own pairs plus fresh affinity pairs. Every refinement
        still goes through the full walk-forward + gates + batch-wide Deflated Sharpe."""
        fam = FAMILIES[cand["family"]]
        spec = self.next_spec(universe, family=cand["family"])
        params = fam.normalize(cand.get("params"))
        over = {}
        for p in fam.params:
            if p.name in ("htf_trend", "vol_regime", "session", "no_weekend", "event_guard", "event_lock", "vol_shock",
                          "exit_mode", "lab_tp", "lab_trail"):
                over[p.name] = [params[p.name], params[p.name]]  # keep the structural genes
                continue
            span = (p.high - p.low) * width
            over[p.name] = [max(p.low, params[p.name] - span), min(p.high, params[p.name] + span)]
        merged = {**over, **spec.get("space_overrides", {})}
        for g in ("htf_trend", "vol_regime", "tp_lock") + CONTEXT_GENES + EXIT_GENES + LAB_EXIT:  # a refinement keeps its structure
            merged[g] = over[g]
        spec["space_overrides"] = merged
        own = [p for p in (cand.get("pairs") or []) if p in universe]
        n = self.s.research.pairs_per_experiment
        spec["pairs"] = sorted((own + [p for p in spec["pairs"] if p not in own])[:max(n, len(own))])
        spec["sides"] = cand.get("sides") or spec["sides"]
        spec["refines"] = cand["id"]
        spec["timeframe"] = cand.get("timeframe") or "1h"
        return spec

    def next_spec(self, universe: list[str], family: str | None = None) -> dict:
        family = family or ucb_pick(self.family_stats(), rng=self.rng)
        fam = FAMILIES[family]
        market = {r["pair"]: r["data"] for r in self.reg.q("SELECT pair, data FROM market")}
        key = "trend_score" if fam.affinity == "trend" else "revert_score"
        ranked = sorted(universe, key=lambda p: -(market.get(p, {}) or {}).get(key, 0.0))

        learnings = self.active_learnings(family)
        overrides: dict = {}
        used: list[str] = []
        n_pairs = self.s.research.pairs_per_experiment
        sides = ["long", "short"]
        apply = bool(learnings) and self.rng.random() < 0.5
        if apply:
            for lr in learnings:
                adj = lr.get("adjustment") or {}
                overrides.update(adj.get("space", {}))
                n_pairs += int(adj.get("extra_pairs", 0))
                if adj.get("sides"):
                    sides = list(adj["sides"])
                used.append(lr["id"])

        # top affinity pairs plus a little randomness to avoid always testing the same set
        pool = ranked[: max(n_pairs + 4, n_pairs)]
        pairs = sorted(self.rng.sample(pool, k=min(n_pairs, len(pool)))) if pool else []
        spec = {
            "family": family,
            "pairs": pairs,
            "sides": sides,
            "space_overrides": overrides,
            "used_learnings": used,
            "epochs": self.s.research.epochs,
            "seed": self.rng.randint(1, 10_000),
            "timeframe": "15m" if family in MULTI_TF and self.rng.random() < 0.5 else self.s.research.timeframe,
        }
        # Where the evidence points, look further: time-series momentum is the one effect the
        # lab, the screener and the literature agree on, and its documented horizons (2–12 weeks)
        # lie beyond 1h bars (lookback ≤ 504 bars = 21 days). Half of its experiments run on 4h,
        # where the same lookback range spans 12–84 days.
        tf_hi = HIGHER_TF.get(family)
        if tf_hi and self.rng.random() < tf_hi[1]:
            spec["timeframe"] = tf_hi[0]
        # Market-context genes (trading hours, weekends, US macro releases) are searched in
        # about a third of new experiments; elsewhere they stay off, so the usual search keeps
        # its size and speed. The bandit, walk-forward and decoys judge the difference.
        for g in LAB_EXIT:  # Strategy Lab exits belong to imported configurations only
            overrides.setdefault(g, [0, 0])
        if self.rng.random() >= 0.35:
            for g in CONTEXT_GENES:
                overrides.setdefault(g, [0, 0])
        # careful-trader exits (lock near TP, before macro releases, on volatility shocks): same idea
        if self.rng.random() >= 0.35:
            for g in EXIT_GENES:
                overrides.setdefault(g, [0, 0])
            overrides.setdefault("tp_lock", [0.75, 0.75])
        return spec
