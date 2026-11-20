"""Strategy lifecycle: candidate → exploration/incubation (small risk, live demo) →
production → retired. Promotion requires *independent* evidence: forward demo trades
that the optimiser never saw. Builds the manifest the trading bot executes."""

from __future__ import annotations

import logging
from datetime import timedelta

from aitrader.families import FAMILIES
from aitrader.learner import live_metrics
from aitrader.manifest import STAGE_PRIORITY, Manifest, Sleeve, write_pairlist
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
        return {"production": self.lc.risk_production, "incubation": self.lc.risk_incubation,
                "eligible": self.lc.risk_incubation,
                "exploration": self.lc.risk_exploration}.get(stage, 0.0)

    # ------------------------------------------------------------------ bootstrap
    def bootstrap(self) -> None:
        """Day-0: run each family with default (unvalidated) parameters at exploration risk
        so the full execution pipeline is exercised while research produces candidates."""
        if self.reg.kv_get("bootstrapped"):
            return
        now = iso()
        for i, fam in enumerate(FAMILIES.values()):
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
            for c in data.get("candidates", []):
                if self.reg.one("SELECT id FROM strategies WHERE id=?", (c["id"],)):
                    continue
                now = iso()
                note = (f"offline batch {data.get('batch_id')} ({data.get('exchange')} data, "
                        f"N={data.get('n_trials_for_dsr')} trials) – needs Bybit forward test")
                self.reg.upsert("strategies", {
                    "id": c["id"], "experiment_id": c.get("experiment", ""), "family": c["family"],
                    "params": c["params"], "pairs": c["pairs"], "sides": c.get("sides", ["long", "short"]),
                    "stage": c["stage"], "score": c.get("score", 0.0), "oos": c.get("oos", {}),
                    "gates": c.get("gates", {}), "live": {}, "created": now, "updated": now,
                    "stage_since": now, "history": [{"ts": now, "to": c["stage"], "reason": note}],
                    "note": note,
                })
                n += 1
        if n:
            self.reg.event("lifecycle", f"imported {n} offline research candidates")
        return n

    # ------------------------------------------------------------------ evaluation
    def update_live(self, equity: float) -> None:
        for st in self.reg.strategies(DEPLOYED + ("retired",)):
            trades = self.reg.q("SELECT * FROM live_trades WHERE sleeve_id=? AND close_date >= ? "
                                "ORDER BY close_date", (st["id"], (st.get("created") or "")[:10]))
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
                    if pf >= 1.1 and pnl > 0:
                        self.reg.set_stage(s["id"], "incubation", f"exploration passed: {n} trades, PF {pf}")
                    else:
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
                recent = self.reg.q("SELECT profit_abs FROM live_trades WHERE sleeve_id=? "
                                    "ORDER BY close_date DESC LIMIT ?", (s["id"], lc.production_window))
                if len(recent) >= lc.production_window:
                    import numpy as np

                    from aitrader.research.metrics import profit_factor
                    rpf = profit_factor(np.array([float(r["profit_abs"] or 0) for r in recent]))
                    if rpf < lc.production_retire_pf:
                        self.reg.set_stage(s["id"], "retired", f"rolling PF {rpf:.2f} over last {len(recent)} trades")
                        continue
                if live.get("max_drawdown", 0) > lc.sleeve_max_dd:
                    self.reg.set_stage(s["id"], "retired", f"sleeve drawdown {live['max_drawdown']:.1%}")

        self._promote()
        self._fill_slots()

    def diverges(self, s: dict, min_trades: int = 20) -> bool:
        """Live mean trade return significantly (2 SE) below the OOS expectation and negative."""
        import numpy as np
        oos_exp = (s.get("oos") or {}).get("expectancy")
        rows = self.reg.q("SELECT profit_ratio FROM live_trades WHERE sleeve_id=?", (s["id"],))
        if oos_exp is None or oos_exp <= 0 or len(rows) < min_trades:
            return False
        r = np.array([float(x["profit_ratio"] or 0) for x in rows])
        se = r.std(ddof=1) / np.sqrt(len(r)) if len(r) > 1 else 0
        return bool(r.mean() < 0 and r.mean() < oos_exp - 2 * se)

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
        n_inc = len(self.reg.strategies(("incubation",)))
        for cand in self.reg.strategies(("validated",)):
            if n_inc >= lc.max_incubation:
                break
            self.reg.set_stage(cand["id"], "incubation", "validated by research gates → forward test")
            n_inc += 1
        n_exp = len(self.reg.strategies(("exploration",)))
        for cand in self.reg.strategies(("exploratory",)):
            if n_exp >= lc.max_exploration:
                break
            self.reg.set_stage(cand["id"], "exploration", "relaxed gates passed → tiny-risk live experiment")
            n_exp += 1
        # Always-on learning: keep the exploration lane busy with the best recent near-misses
        # (profitable out-of-sample but failed a strict gate) so live evidence keeps flowing.
        if n_exp < lc.max_exploration:
            for cand in self.near_misses(lc.max_exploration - n_exp):
                self.reg.set_stage(cand["id"], "exploration",
                                   "always-on exploration: near-miss (positive OOS, failed a strict gate)")
                n_exp += 1
        self.ensure_activity()

    def near_misses(self, k: int, days: int = 30) -> list[dict]:
        cutoff = iso(utcnow() - timedelta(days=days))
        out = []
        for r in self.reg.q("SELECT * FROM strategies WHERE stage='rejected' AND created >= ? "
                            "ORDER BY created DESC LIMIT 200", (cutoff,)):
            o = r.get("oos") or {}
            if r.get("pairs") and o.get("trades", 0) >= 10 and o.get("total_return", 0) > 0 \
                    and o.get("profit_factor", 0) >= 1.0 and not str(r["id"]).startswith("rnd-"):
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
    def build_manifest(self, open_trades: list[dict], excluded: set[str], paused: bool) -> Manifest:
        rows = self.reg.strategies(DEPLOYED)
        rows.sort(key=lambda r: (-STAGE_PRIORITY.get("incubation" if r["stage"] == "eligible" else r["stage"], 0),
                                 -(r.get("score") or 0)))
        taken: set[str] = set()
        sleeves: list[Sleeve] = []
        for r in rows:
            mine = [p for p in (r.get("pairs") or []) if p not in taken and p not in excluded]
            mine = mine[: self.lc.max_pairs_per_sleeve]
            if not mine:
                continue
            taken.update(mine)
            stage = "incubation" if r["stage"] == "eligible" else r["stage"]
            sleeves.append(Sleeve(id=r["id"], family=r["family"], params=r["params"], pairs=mine,
                                  stage=stage,
                                  risk=round(self.risk_for(r["stage"]) * (self.risk_multiplier(r)
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
