"""Strategy lifecycle: candidate → exploration/incubation (small risk, live demo) →
production → retired. Promotion requires *independent* evidence: forward demo trades
that the optimiser never saw. Builds the manifest the trading bot executes."""

from __future__ import annotations

import logging
import math
from datetime import timedelta

from aitrader.families import FAMILIES
from aitrader.learner import live_metrics
from aitrader.manifest import STAGE_PRIORITY, Manifest, Sleeve, write_pairlist
from aitrader.realism import real_pnl, real_ratio
from aitrader.registry import Registry
from aitrader.settings import Settings
from aitrader.util import iso, parse_dt, utcnow

log = logging.getLogger(__name__)

BOOT_PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT",
              "DOGE/USDT:USDT", "BNB/USDT:USDT", "ADA/USDT:USDT", "LINK/USDT:USDT"]
DEPLOYED = ("production", "eligible", "incubation", "exploration")


def _days_since(ts: str | None) -> float:
    dt = parse_dt(ts)
    return (utcnow() - dt).total_seconds() / 86400 if dt else 0.0


class Lifecycle:
    def __init__(self, settings: Settings, registry: Registry):
        self.s = settings
        self.lc = settings.lifecycle
        self.reg = registry

    def risk_for(self, stage: str) -> float:
        requested, cap = {
            "production": (self.lc.risk_production, 0.0075),
            "incubation": (self.lc.risk_incubation, 0.0025),
            "eligible": (self.lc.risk_incubation, 0.0025),
            "exploration": (self.lc.risk_exploration, 0.001),
        }.get(stage, (0.0, 0.0))
        return min(max(requested, 0.0), cap) if math.isfinite(requested) else 0.0

    # ------------------------------------------------------------------ bootstrap
    def bootstrap(self) -> None:
        """Day-0: run each family with default (unvalidated) parameters at exploration risk
        so the full execution pipeline is exercised while research produces candidates."""
        if self.reg.kv_get("bootstrapped"):
            return
        now = iso()
        for i, fam in enumerate(list(FAMILIES.values())[:4]):  # day-0 placeholders, 2 pairs each
            sid = f"boot-{fam.name}"
            self.reg.upsert("strategies", {
                "id": sid, "experiment_id": "", "family": fam.name, "params": fam.defaults(),
                "pairs": BOOT_PAIRS[2 * i: 2 * i + 2], "sides": ["long", "short"],
                "stage": "exploration", "score": 0.0, "oos": {}, "gates": {}, "live": {},
                "created": now, "updated": now, "stage_since": now,
                "history": [{"ts": now, "to": "exploration", "reason": "bootstrap defaults (unvalidated)"}],
                "note": "Unvalidated default parameters – pipeline check at minimum risk",
            })
        self.reg.kv_set("bootstrapped", now)
        self.reg.event("lifecycle", "bootstrapped exploration sleeves with default parameters")

    def import_offline_candidates(self, directory) -> int:
        """Import candidates from offline research batches (research/imports/*.json).
        They enter as validated/exploratory and must pass Bybit Demo forward tests."""
        import json
        from pathlib import Path
        n = 0
        for f in sorted(Path(directory).glob("*.json")):
            try:
                data = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            n += self.import_batch(data, announce=False)
        if n:
            self.reg.event("lifecycle", f"imported {n} offline research candidates")
        return n

    def import_batch(self, data: dict, announce: bool = True) -> int:
        """One research batch (GitHub research lab or offline file) → candidates."""
        n = 0
        batch = data.get("batch_id")
        current = {c["id"] for c in data.get("candidates", [])}
        if batch:  # a re-filtered batch file also retracts candidates it no longer contains
            for r in self.reg.q("SELECT id FROM strategies WHERE id LIKE ? AND stage IN ('exploratory','validated')",
                                (f"{batch}-%",)):
                if r["id"] not in current:
                    self.reg.set_stage(r["id"], "rejected", "retracted by stricter re-filter of its batch")
        for c in data.get("candidates", []):
            if self.reg.one("SELECT id FROM strategies WHERE id=?", (c["id"],)):
                continue
            now = iso()
            note = (f"research batch {batch} ({data.get('exchange')} data, "
                    f"N={data.get('n_trials_for_dsr')} trials) – needs Bybit forward test")
            self.reg.upsert("strategies", {
                "id": c["id"], "experiment_id": c.get("experiment", ""), "family": c["family"],
                "params": c["params"], "pairs": c["pairs"], "sides": c.get("sides", ["long", "short"]),
                "stage": c["stage"], "score": c.get("score", 0.0), "oos": c.get("oos", {}),
                "gates": c.get("gates", {}), "live": {}, "created": now, "updated": now,
                "stage_since": now, "history": [{"ts": now, "to": c["stage"], "reason": note}],
                "note": note,
            })
            self.reg.event("research", f"{c['id']} ({c.get('variant', c['family'])}) imported as {c['stage']} — "
                           f"OOS PF {(c.get('oos') or {}).get('profit_factor')}, Sharpe {(c.get('oos') or {}).get('sharpe')}",
                           data={"strategy": c["id"]})
            n += 1
        if n and announce:
            self.reg.event("lifecycle", f"imported {n} candidates from research batch {batch}")
        return n

    # ------------------------------------------------------------------ evaluation
    def stage_trades(self, s: dict, limit: int = -1) -> list[dict]:
        return self.reg.q(
            "SELECT * FROM live_trades WHERE sleeve_id=? AND julianday(open_date) >= julianday(?) "
            "ORDER BY julianday(close_date) DESC LIMIT ?",
            (s["id"], s.get("stage_since"), limit),
        )[::-1]

    def update_live(self, equity: float) -> None:
        for st in self.reg.strategies(DEPLOYED + ("retired",)):
            trades = self.stage_trades(st)
            self.reg.update("strategies", st["id"], {"live": live_metrics(trades, equity)})

    def evaluate(self, equity: float) -> None:
        lc = self.lc
        self.update_live(equity)
        strategies = {s["id"]: s for s in self.reg.strategies()}

        for s in [x for x in strategies.values() if x["stage"] in DEPLOYED]:
            live = s.get("live") or {}
            n, pf = live.get("trades", 0), live.get("profit_factor", 0.0)
            age = _days_since(s.get("stage_since"))
            pnl = live.get("pnl", 0.0)
            if s["stage"] == "exploration":
                if n >= lc.exploration_min_trades:
                    gates = s.get("gates") or {}
                    has_oos = ((s.get("oos") or {}).get("protocol") == "fixed_365x90"
                               and "fold_consistency" in gates and all(g["pass"] for g in gates.values()))
                    has_capacity = len(self.reg.strategies(("incubation", "eligible"))) < lc.max_incubation
                    if has_oos and has_capacity and pf >= 1.1 and pnl > 0 and not self.diverges(s):
                        self.reg.set_stage(s["id"], "incubation", f"exploration passed: {n} trades, PF {pf}")
                    elif pf < 1.1 or pnl <= 0 or age > lc.exploration_max_days:
                        self.reg.set_stage(s["id"], "retired", f"exploration failed: {n} trades, PF {pf}")
                elif age > lc.exploration_max_days:
                    self.reg.set_stage(s["id"], "retired", f"exploration inconclusive after {age:.0f}d ({n} trades)")
            elif s["stage"] in ("incubation", "eligible"):
                if s["stage"] == "incubation" and n >= lc.incubation_min_trades \
                        and age >= lc.incubation_min_days and pf >= lc.promote_min_pf and pnl > 0 \
                        and live.get("max_drawdown", 1) <= lc.sleeve_max_dd:
                    self.reg.set_stage(s["id"], "eligible", f"forward test passed: {n} trades, PF {pf}")
                elif n >= lc.incubation_min_trades and pf < lc.retire_max_pf:
                    self.reg.set_stage(s["id"], "retired", f"forward test failed: {n} trades, PF {pf}")
                elif s["stage"] == "incubation" and age > lc.incubation_max_days:
                    self.reg.set_stage(s["id"], "retired", f"incubation timed out ({n} trades, PF {pf})")
            if s["stage"] in ("incubation", "eligible", "production") and self.diverges(s):
                self.reg.set_stage(s["id"], "retired", "live results diverge from out-of-sample expectation")
                continue
            if s["stage"] == "production":
                recent = self.stage_trades(s, lc.production_window)
                if len(recent) >= lc.production_window:
                    import numpy as np

                    from aitrader.research.metrics import profit_factor
                    rpf = profit_factor(np.array([real_pnl(r) for r in recent]))
                    if rpf < lc.production_retire_pf:
                        self.reg.set_stage(s["id"], "retired", f"rolling PF {rpf:.2f} over last {len(recent)} trades")
                        continue
                if live.get("max_drawdown", 0) > lc.sleeve_max_dd:
                    self.reg.set_stage(s["id"], "retired", f"sleeve drawdown {live['max_drawdown']:.1%}")

        self._promote()
        self._fill_slots()

    def diverges(self, s: dict, min_trades: int = 20, rows: list[dict] | None = None) -> bool:
        """Detect material deterioration in post-promotion returns versus the OOS test."""
        import numpy as np
        oos_exp = (s.get("oos") or {}).get("expectancy")
        rows = self.stage_trades(s) if rows is None else rows
        if oos_exp is None or oos_exp <= 0 or len(rows) < min_trades:
            return False
        r = np.array([real_ratio(x) for x in rows])
        se = r.std(ddof=1) / np.sqrt(len(r)) if len(r) > 1 else 0
        return bool(r.mean() < oos_exp - 2 * se)

    def risk_multiplier(self, s: dict, prior: int = 20) -> float:
        """Shift capital towards sleeves with proven live edge (shrunk towards PF=1)."""
        live = s.get("live") or {}
        n, pf = int(live.get("trades", 0)), float(live.get("profit_factor", 1.0) or 1.0)
        if n < 10:
            return 1.0
        shrunk = (n * min(pf, 3.0) + prior * 1.0) / (n + prior)
        return round(min(max(shrunk, 0.5), 1.5), 3)

    def _promote(self) -> None:
        lc = self.lc
        prod = self.reg.strategies(("production",))
        for cand in self.reg.strategies(("eligible",)):
            if len(prod) < lc.max_production:
                self.reg.set_stage(cand["id"], "production", "promoted: OOS + forward demo validation passed")
                prod.append(cand)
                continue
            weakest = min(prod, key=lambda x: x.get("score") or 0)
            if (cand.get("score") or 0) > 1.2 * (weakest.get("score") or 0):
                self.reg.set_stage(weakest["id"], "retired", f"replaced by stronger {cand['id']}")
                self.reg.set_stage(cand["id"], "production", f"promoted, replacing {weakest['id']}")
                prod = [p for p in prod if p["id"] != weakest["id"]] + [cand]

    def _fill_slots(self) -> None:
        lc = self.lc
        n_exp = len(self.reg.strategies(("exploration",)))
        candidates = self.reg.strategies(("validated",)) + self.reg.strategies(("exploratory",))
        for cand in candidates:
            if self._family_full(cand["family"]):
                if not self._displace_placeholder(cand, same_family=True):
                    continue
                n_exp = len(self.reg.strategies(("exploration",)))
            if n_exp >= lc.max_exploration and not self._displace_placeholder(cand):
                break
            self.reg.set_stage(cand["id"], "exploration", "forward test begins at exploration risk")
            n_exp = len(self.reg.strategies(("exploration",)))
        # Always-on learning: keep the exploration lane busy with the best recent near-misses
        # (profitable out-of-sample but failed a strict gate) so live evidence keeps flowing.
        if n_exp < lc.max_exploration:
            for cand in self.near_misses(lc.max_exploration - n_exp):
                if self._family_full(cand["family"]):
                    continue
                self.reg.set_stage(cand["id"], "exploration",
                                   "always-on exploration: near-miss (positive OOS, failed a strict gate)")
                n_exp += 1
        self.ensure_activity()

    def _family_full(self, family: str, cap: int = 2) -> bool:
        """Diversification: at most `cap` deployed sleeves per strategy family."""
        return sum(1 for r in self.reg.strategies(DEPLOYED) if r["family"] == family) >= cap

    def _displace_placeholder(self, cand: dict, same_family: bool = False) -> bool:
        """Research-backed candidates replace unvalidated placeholders (bootstrap defaults,
        random explorers) unless the placeholder has already shown a live edge."""
        for r in sorted(self.reg.strategies(("exploration",)), key=lambda x: x.get("stage_since") or ""):
            if same_family and r["family"] != cand["family"]:
                continue
            if not (str(r["id"]).startswith("boot-") or str(r["id"]).startswith("rnd-")):
                continue
            live = r.get("live") or {}
            if live.get("trades", 0) >= 10 and live.get("profit_factor", 0) >= 1.1:
                continue  # earned its place with live evidence
            self.reg.set_stage(r["id"], "retired", f"superseded by research candidate {cand['id']}")
            return True
        return False

    def near_misses(self, k: int, days: int = 30) -> list[dict]:
        cutoff = iso(utcnow() - timedelta(days=days))
        out = []
        for r in self.reg.q("SELECT * FROM strategies WHERE stage='rejected' AND created >= ? "
                            "ORDER BY created DESC LIMIT 200", (cutoff,)):
            o = r.get("oos") or {}
            if r.get("pairs") and o.get("trades", 0) >= 15 and o.get("total_return", 0) > 0 \
                    and o.get("profit_factor", 0) >= 1.05 and o.get("sharpe", 0) >= 0.3 \
                    and not str(r["id"]).startswith("rnd-"):
                out.append(r)
        out.sort(key=lambda r: -(r["oos"].get("sharpe", 0)))
        return out[:k]

    def ensure_activity(self) -> None:
        """If nothing at all is trading, launch random-variant explorers on liquid pairs so the
        system keeps generating live evidence instead of going idle."""
        if self.reg.strategies(DEPLOYED):
            return
        import random
        uni = (self.reg.kv_get("universe") or {}).get("pairs") or BOOT_PAIRS
        rng = random.Random()
        for _ in range(2):
            fam = rng.choice(list(FAMILIES.values()))
            params = fam.perturb(fam.defaults(), 0.25, rng)
            pairs = rng.sample(uni, k=min(3, len(uni)))
            sid = f"rnd-{fam.name[:5]}-{rng.randrange(16**6):06x}"
            now = iso()
            self.reg.upsert("strategies", {
                "id": sid, "experiment_id": "", "family": fam.name, "params": params, "pairs": pairs,
                "sides": ["long", "short"], "stage": "exploration", "score": 0.0,
                "oos": {"variant": fam.variant(params)}, "gates": {}, "live": {}, "created": now,
                "updated": now, "stage_since": now,
                "history": [{"ts": now, "to": "exploration", "reason": "random explorer (nothing else trading)"}],
                "note": "Random variant at exploration risk – keeps live learning active",
            })
            self.reg.event("lifecycle", f"{sid}: random explorer launched ({fam.variant(params)}) on {pairs}")

    # ------------------------------------------------------------------ manifest
    def portfolio_scale(self, target_daily_vol: float = 0.015, days: int = 20) -> float:
        """Volatility targeting: if the account's realised daily volatility exceeds the
        target, every sleeve's risk is scaled down proportionally (never up, floor 0.5)."""
        import numpy as np
        rows = self.reg.q("SELECT ts, equity FROM equity ORDER BY ts DESC LIMIT ?", (days * 144 + 1,))
        if len(rows) < 3 * 144:
            return 1.0
        daily = {}
        for r in rows:  # last snapshot per day
            daily.setdefault(r["ts"][:10], float(r["equity"]))
        eq = np.array([v for _, v in sorted(daily.items())])
        if len(eq) < 4 or (eq <= 0).any():
            return 1.0
        vol = float(np.std(np.diff(np.log(eq)), ddof=1))
        scale = 1.0 if vol <= target_daily_vol else max(0.5, target_daily_vol / vol)
        self.reg.kv_set("risk_scale", {"scale": round(scale, 3), "daily_vol": round(vol, 5), "ts": iso()})
        return scale

    def correlation_penalty(self, ids: list[str], max_corr: float = 0.7, min_days: int = 20) -> dict[str, float]:
        """Two live sleeves whose daily P&L moves together are one bet: halve the weaker."""
        import pandas as pd
        series = {}
        for sid in ids:
            rows = self.reg.q("SELECT close_date, profit_abs FROM live_trades WHERE sleeve_id=?", (sid,))
            if len(rows) >= 10:
                s = pd.Series([float(r["profit_abs"] or 0) for r in rows],
                              index=pd.to_datetime([r["close_date"] for r in rows], utc=True, errors="coerce"))
                series[sid] = s[s.index.notna()].resample("1D").sum()
        out: dict[str, float] = {}
        if len(series) < 2:
            return out
        df = pd.DataFrame(series).fillna(0.0)
        if len(df) < min_days:
            return out
        corr = df.corr()
        score = {r["id"]: float(r.get("score") or 0) for r in self.reg.strategies(DEPLOYED)}
        cols = list(corr.columns)
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                if corr.loc[a, b] > max_corr:
                    weaker = a if score.get(a, 0) < score.get(b, 0) else b
                    out[weaker] = 0.5
        return out

    def build_manifest(self, open_trades: list[dict], excluded: set[str], paused: bool) -> Manifest:
        rows = self.reg.strategies(DEPLOYED)
        scale = self.portfolio_scale()
        penalty = self.correlation_penalty([r["id"] for r in rows if r["stage"] in ("production", "incubation", "eligible")])
        rows.sort(key=lambda r: (-STAGE_PRIORITY.get("incubation" if r["stage"] == "eligible" else r["stage"], 0),
                                 -(r.get("score") or 0)))
        taken: set[str] = set()
        family_count: dict[str, int] = {}
        sleeves: list[Sleeve] = []
        for r in rows:
            family = r["family"]
            if family_count.get(family, 0) >= 2:
                continue
            mine = [p for p in (r.get("pairs") or []) if p not in taken and p not in excluded]
            mine = mine[: self.lc.max_pairs_per_sleeve]
            if not mine:
                continue
            if (r.get("oos") or {}).get("protocol") == "fixed_365x90" and mine != r["pairs"]:
                continue  # the OOS reference applies to the complete, tested portfolio
            taken.update(mine)
            family_count[family] = family_count.get(family, 0) + 1
            stage = "incubation" if r["stage"] == "eligible" else r["stage"]
            sleeves.append(Sleeve(id=r["id"], family=r["family"], params=r["params"], pairs=mine,
                                  stage=stage,
                                  risk=round(self.risk_for(r["stage"]) * scale * penalty.get(r["id"], 1.0)
                                             * (min(1.0, self.risk_multiplier(r))
                                                if r["stage"] in ("production", "incubation", "eligible") else 1.0), 6),
                                  leverage=self.lc.leverage, sides=r.get("sides") or ["long", "short"],
                                  score=float(r.get("score") or 0.0)))
        # retired sleeves that still hold positions keep managing them (no new entries)
        live_ids = {s.id for s in sleeves}
        for t in open_trades:
            tag = t.get("enter_tag")
            if tag and tag not in live_ids:
                r = self.reg.one("SELECT * FROM strategies WHERE id=?", (tag,))
                if r:
                    sleeves.append(Sleeve(id=r["id"], family=r["family"], params=r["params"],
                                          pairs=[], stage="closing", risk=0.0, leverage=self.lc.leverage,
                                          sides=r.get("sides") or ["long", "short"]))
                    live_ids.add(tag)
        return Manifest(sleeves=sleeves, entries_paused=paused)

    def write(self, manifest: Manifest, open_trades: list[dict]) -> bool:
        """Persist manifest + pairlist if the content changed. Returns True if changed."""
        old = Manifest.load(self.s.manifest_path)
        same = (old.to_dict()["sleeves"] == manifest.to_dict()["sleeves"]
                and old.entries_paused == manifest.entries_paused)
        pairs = manifest.all_pairs()
        for t in open_trades:
            if t.get("pair") and t["pair"] not in pairs:
                pairs.append(t["pair"])
        write_pairlist(self.s.pairlist_path, pairs or ["BTC/USDT:USDT"])
        if same and self.s.manifest_path.exists():
            return False
        manifest.version = old.version
        manifest.save(self.s.manifest_path)
        self.reg.event("lifecycle", f"manifest v{manifest.version}: "
                       + ", ".join(f"{s.id}[{s.stage}:{len(s.pairs)}]" for s in manifest.sleeves))
        return True
