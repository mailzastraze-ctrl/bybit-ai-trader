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

from aitrader.families import FAMILIES
from aitrader.registry import Registry
from aitrader.settings import Settings
from aitrader.util import iso


def ucb_pick(stats: dict[str, tuple[int, float]], c: float = 0.6, rng: random.Random | None = None) -> str:
    """stats: family -> (n_experiments, mean_reward). Untried families first."""
    rng = rng or random.Random()
    untried = [f for f, (n, _) in stats.items() if n == 0]
    if untried:
        return rng.choice(untried)
    total = sum(n for n, _ in stats.values())
    return max(stats, key=lambda f: stats[f][1] + c * math.sqrt(math.log(total) / stats[f][0]))


class Generator:
    def __init__(self, settings: Settings, registry: Registry, seed: int | None = None):
        self.s = settings
        self.reg = registry
        self.rng = random.Random(seed)

    def family_stats(self) -> dict[str, tuple[int, float]]:
        stats = {f: (0, 0.0) for f in FAMILIES}
        rows = self.reg.q("SELECT family, result, status FROM experiments WHERE status IN ('done','failed')")
        acc: dict[str, list[float]] = {f: [] for f in FAMILIES}
        for r in rows:
            if r["family"] not in acc:
                continue
            res = r.get("result") if isinstance(r.get("result"), dict) else {}
            reward = res.get("score", 0.0) if res.get("verdict") in ("validated", "exploratory") else 0.0
            acc[r["family"]].append(float(reward))
        for f, xs in acc.items():
            if xs:
                stats[f] = (len(xs), sum(xs) / len(xs))
        return stats

    def active_learnings(self, family: str) -> list[dict]:
        now = iso()
        rows = self.reg.q("SELECT * FROM learnings WHERE active=1 AND scope IN ('family','research') AND key=?",
                          (family,))
        return [r for r in rows if not r.get("expires") or r["expires"] > now]

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
        return {
            "family": family,
            "pairs": pairs,
            "sides": sides,
            "space_overrides": overrides,
            "used_learnings": used,
            "epochs": self.s.research.epochs,
            "seed": self.rng.randint(1, 10_000),
            "timeframe": self.s.research.timeframe,
        }
