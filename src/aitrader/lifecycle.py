"""Strategy lifecycle: candidate → exploration/incubation (small risk, live demo) →
production → retired. Promotion requires *independent* evidence: forward demo trades
that the optimiser never saw. Builds the manifest the trading bot executes."""

from __future__ import annotations

import logging
from datetime import timedelta

from aitrader import evidence as EV
from aitrader.families import FAMILIES
from aitrader.learner import live_metrics
from aitrader.manifest import STAGE_PRIORITY, Manifest, Sleeve, write_pairlist
from aitrader.realism import real_pnl
from aitrader.registry import Registry
from aitrader.settings import Settings
from aitrader.util import iso, parse_dt, utcnow

log = logging.getLogger(__name__)
# bot candles = 15m (config/trade.json); higher timeframes are computed on their own candles
# and merged without look-ahead (informative pairs): 1h research and the 2h–12h autopilot
BOT_TIMEFRAMES = ("15m", "1h", "2h", "4h", "6h", "12h")

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

    def import_external(self, directory) -> int:
        """Strategies brought in from outside (research/external/*.json, e.g. the owner's own
        Strategy Lab). They are frozen at import and go through the same honest tests:
        walk-forward with the fixed configuration and the forward test on unseen data."""
        import json
        from pathlib import Path
        n = 0
        for f in sorted(Path(directory).glob("*.json")):
            try:
                d = json.loads(f.read_text())
                fam = FAMILIES[d["family"]]
            except (OSError, json.JSONDecodeError, KeyError):
                continue
            old = d.get("supersedes")  # a corrected version of an earlier import (e.g. exact exits)
            if old and self.reg.one("SELECT id FROM strategies WHERE id=? AND stage != 'retired'", (old,)):
                self.reg.set_stage(old, "retired", f"superseded by {d['id']} ({d.get('supersede_reason', 'corrected import')})")
            if self.reg.one("SELECT id FROM strategies WHERE id=?", (d["id"],)):
                continue
            now = iso()
            note = f"external: {d.get('source', 'outside')} – frozen at import, forward test from now"
            self.reg.upsert("strategies", {
                "id": d["id"], "experiment_id": "", "family": fam.name, "params": fam.normalize(d.get("params")),
                "pairs": d.get("pairs") or [], "sides": d.get("sides") or ["long", "short"], "stage": "exploratory",
                "score": 0.0, "oos": {"timeframe": d.get("timeframe") or "1h", "external": True,
                                      "benchmark": bool(d.get("benchmark")), "owner": bool(d.get("owner")),
                                      "claimed": d.get("claimed") or {}, "source": d.get("source"),
                                      "variant": f"{fam.name} (external, {', '.join(p.split('/')[0] for p in d.get('pairs') or [])} "
                                                 f"{d.get('timeframe') or '1h'})"},
                "gates": {}, "live": {}, "created": now, "updated": now, "stage_since": now,
                "history": [{"ts": now, "to": "exploratory", "reason": note}], "note": note})
            self.reg.event("lifecycle", f"{d['id']}: {note}", data={"strategy": d["id"]})
            n += 1
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
    def update_live(self, equity: float) -> None:
        btc = EV.btc_returns(self.reg.kv_get("btc_daily"))
        for st in self.reg.strategies(DEPLOYED + ("retired",)):
            trades = self.reg.q("SELECT * FROM live_trades WHERE sleeve_id=? AND close_date >= ? "
                                "ORDER BY close_date", (st["id"], (st.get("created") or "")[:10]))
            live = live_metrics(trades, equity)
            live["alpha"] = (self.market_split(trades, equity, btc) if st["stage"] in DEPLOYED
                             else (st.get("live") or {}).get("alpha"))  # retired: frozen, saves CPU
            self.reg.update("strategies", st["id"], {"live": live})

    @staticmethod
    def market_split(trades: list[dict], equity: float, btc) -> dict:
        """Beta to BTC and the alpha left after it, on calendar-day realistic returns.
        A short sleeve in a falling market earns money without any skill; alpha says how much
        of the result the market does not explain."""
        empty = {"days": 0, "alpha": None, "beta": None, "alpha_t": None, "alpha_ann": None}
        if not trades or btc is None or not len(btc):
            return empty | {"note": "нет данных BTC" if trades else "нет сделок"}
        try:  # analytics must never break the manager loop; unmeasurable alpha only makes promotion wait
            daily = EV.daily_returns(trades, equity, real_pnl, end=utcnow())
            return EV.alpha_beta(daily, btc)
        except Exception as e:  # noqa: BLE001
            log.warning("alpha for %d trades failed: %s", len(trades), e)
            return empty | {"note": "ошибка расчёта"}

    @staticmethod
    def alpha_state(live: dict) -> str:
        """'ok' – positive alpha estimate; 'none' – alpha not measurable (no BTC data yet, too
        few days); 'beta' – the market explains the result. Promotion to production needs 'ok'
        (slow to trust): profit fully explained by the market move is beta, which costs nothing."""
        a = (live or {}).get("alpha") or {}
        if a.get("alpha") is None:
            return "none"
        return "ok" if a["alpha"] > 0 else "beta"

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
                passed = s["stage"] == "incubation" and n >= lc.incubation_min_trades \
                    and age >= lc.incubation_min_days and pf >= lc.promote_min_pf and pnl > 0 \
                    and live.get("max_drawdown", 1) <= lc.sleeve_max_dd
                alpha = self.alpha_state(live)
                if passed and alpha == "ok":
                    a = live["alpha"]
                    self.reg.set_stage(s["id"], "eligible", f"forward test passed: {n} trades, PF {pf}, "
                                       f"alpha over BTC {a.get('alpha_ann')}/yr (β {a.get('beta')})")
                elif n >= lc.incubation_min_trades and pf < lc.retire_max_pf:
                    self.reg.set_stage(s["id"], "retired", f"forward test failed: {n} trades, PF {pf}")
                elif passed and alpha == "none":
                    pass  # profitable and alpha not measurable yet (BTC data outage): wait, never retire for it
                elif s["stage"] == "incubation" and age > lc.incubation_max_days:
                    why = " – profitable, but the market (BTC beta) explains it: no alpha" if passed else ""
                    self.reg.set_stage(s["id"], "retired", f"incubation timed out ({n} trades, PF {pf}){why}")
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
        rows = self.reg.q("SELECT profit_ratio, profit_abs, stake_amount, leverage FROM live_trades WHERE sleeve_id=?",
                          (s["id"],))
        if oos_exp is None or oos_exp <= 0 or len(rows) < min_trades:
            return False
        from aitrader.realism import real_ratio
        r = np.array([real_ratio(x) for x in rows])
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
        for cand in sorted(self.reg.strategies(("validated",)), key=lambda c: self.evidence_rank(c), reverse=True):
            if n_inc >= lc.max_incubation:
                break
            if not self.tradable_tf(cand) or self._family_full(cand, proven=True):
                continue
            self.reg.set_stage(cand["id"], "incubation", "validated by research gates → forward test")
            n_inc += 1
        n_exp = len(self.reg.strategies(("exploration",)))
        # queue by evidence: forward-proven first, then autopilot, then research score
        exploratory = sorted(self.reg.strategies(("exploratory",)), key=lambda c: self.evidence_rank(c), reverse=True)
        for cand in exploratory:
            if not self.tradable_tf(cand) or self._family_full(cand):
                continue
            if n_exp >= lc.max_exploration and not self._displace_for(cand):
                break
            self.reg.set_stage(cand["id"], "exploration", "relaxed gates passed → tiny-risk live experiment")
            n_exp = len(self.reg.strategies(("exploration",)))
        # Always-on learning: keep the exploration lane busy with the best recent near-misses
        # (profitable out-of-sample but failed a strict gate) so live evidence keeps flowing.
        if n_exp < lc.max_exploration:
            for cand in self.near_misses(lc.max_exploration - n_exp):
                if self._family_full(cand):
                    continue
                self.reg.set_stage(cand["id"], "exploration",
                                   "always-on exploration: near-miss (positive OOS, failed a strict gate)")
                n_exp += 1
        self.ensure_activity()

    @staticmethod
    def strategy_tf(st: dict) -> str:
        return (st.get("oos") or {}).get("timeframe") or "1h"

    @staticmethod
    def tradable_tf(st: dict) -> bool:
        """One demo bot runs on 15m candles and also hosts strategies of higher timeframes
        (1h research, 2h–12h autopilot), each computed on its own candles and merged without
        look-ahead, so every research timeframe can trade."""
        return Lifecycle.strategy_tf(st) in BOT_TIMEFRAMES

    def _family_full(self, cand, cap: int | None = None, proven: bool = False) -> bool:
        """Diversification: at most `max_family_per_coin` sleeves of one family on the same coin;
        for unproven exploration also at most `max_family_sleeves` per family in total. Proven
        strategies of one family on *different* coins all trade (each proved itself on its own
        coin); their combined risk is handled by the proven budget and the side cap."""
        family = cand["family"] if isinstance(cand, dict) else cand
        cap = cap or self.lc.max_family_sleeves
        mine = [r for r in self.reg.strategies(DEPLOYED)
                if r["family"] == family and not str(r["id"]).startswith(("boot-", "rnd-"))]
        if not proven and sum(1 for r in mine if r["stage"] == "exploration") >= cap:
            return True
        if isinstance(cand, dict) and cand.get("pairs"):  # every one of its coins already taken by the family
            return all(sum(1 for r in mine if p in (r.get("pairs") or [])) >= self.lc.max_family_per_coin
                       for p in cand["pairs"])
        return False

    # ------------------------------------------------------------------ rotation by evidence
    @staticmethod
    def _near_miss(st: dict) -> bool:
        return any("near-miss" in str(h.get("reason", "")) for h in (st.get("history") or []))

    def evidence_rank(self, st: dict) -> tuple:
        """How much a strategy has shown, best first: 3 forward-proven on unseen data, 2 found by
        the autopilot (seven checks + decoys) or brought by the owner from his Strategy Lab,
        1 research candidate, 0 near-miss/placeholder."""
        o = st.get("oos") or {}
        fw = o.get("forward") or {}
        if str(st["id"]).startswith("fw-") or ((fw.get("trades") or 0) >= 20 and (fw.get("pf") or 0) >= 1.3):
            cls = 3
        elif self.autopilot(st) or o.get("owner"):
            cls = 2
        elif str(st["id"]).startswith(("boot-", "rnd-")) or self._near_miss(st):
            cls = 0
        else:
            cls = 1
        return (cls, float(st.get("score") or 0.0))

    def _displace_for(self, cand: dict) -> bool:
        """Rotation by evidence. A full exploration lane makes room for a stronger candidate by
        moving out a sleeve that holds its slot without evidence: a placeholder, a sleeve with
        < 3 trades after `rotate_idle_days`, or (for an autopilot candidate) an ordinary sleeve
        without a live edge. Sleeves that earned their place live (≥ 10 trades, PF ≥ 1.1) are
        never moved. A rotated research candidate goes back to the queue, it did not fail."""
        mine = self.evidence_rank(cand)
        victims = []
        for r in self.reg.strategies(("exploration",)):
            live = r.get("live") or {}
            n = int(live.get("trades", 0) or 0)
            if n >= 10 and live.get("profit_factor", 0) >= 1.1:
                continue  # earned its place with live evidence
            placeholder = str(r["id"]).startswith(("boot-", "rnd-"))
            age = _days_since(r.get("stage_since"))
            idle = age >= self.lc.rotate_idle_days and n < 3
            theirs = self.evidence_rank(r)
            autopilot_rule = mine[0] >= 2 and theirs[0] < 2 and n < 10
            outclassed = self.outclasses(mine, theirs) and n < 10  # best first: a clearly better candidate
            if not (placeholder or idle or autopilot_rule or outclassed):
                continue
            if not placeholder and theirs >= mine:
                continue  # only a stronger candidate may take the slot
            victims.append((0 if placeholder else 1 if idle else 2, theirs, n, -age, r))
        if not victims:
            return False
        victims.sort(key=lambda v: v[:4])  # placeholders, then sleeves that had their week and did not trade, then the weakest
        r = victims[0][4]
        n = int((r.get("live") or {}).get("trades", 0) or 0)
        why = f"rotated out: {n} trades in {_days_since(r.get('stage_since')):.0f} days, slot given to {cand['id']}"
        if str(r["id"]).startswith(("boot-", "rnd-")) or self._near_miss(r):
            self.reg.set_stage(r["id"], "retired", f"superseded by research candidate {cand['id']}" if not self._near_miss(r) else why)
        else:
            self.reg.set_stage(r["id"], "exploratory", why + " – back in the queue")
        return True

    @staticmethod
    def outclasses(mine: tuple, theirs: tuple) -> bool:
        """'Clearly better' with a margin, so slots do not flip back and forth on noise: a higher
        evidence class, or the same class with a research score ≥ 1.5× and ≥ 0.2 higher."""
        if mine[0] != theirs[0]:
            return mine[0] > theirs[0]
        return mine[1] >= max(1.5 * theirs[1], theirs[1] + 0.2)

    @staticmethod
    def autopilot(st: dict) -> bool:
        return bool((st.get("oos") or {}).get("autopilot"))

    def near_misses(self, k: int, days: int = 30) -> list[dict]:
        cutoff = iso(utcnow() - timedelta(days=days))
        out = []
        for r in self.reg.q("SELECT * FROM strategies WHERE stage='rejected' AND created >= ? "
                            "ORDER BY created DESC LIMIT 200", (cutoff,)):
            o = r.get("oos") or {}
            if r.get("pairs") and self.tradable_tf(r) and o.get("trades", 0) >= 15 and o.get("total_return", 0) > 0 \
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

    def proven_scale(self, rows: list[dict], concurrency: float = 0.5) -> float:
        """All proven strategies hunt for entries at the same time, each on its own coins. Their
        per-trade risk is scaled so that, with half of their coins in a trade at once, the open
        risk stays within `proven_risk_budget` – no strategy is shut out because others entered
        first. With a handful of proven sleeves this is 1.0 (nothing changes); it only shrinks
        sizes when many strategies have proven themselves."""
        proven = [r for r in rows if r["stage"] in ("production", "incubation", "eligible")]
        potential = sum(self.risk_for(r["stage"]) * self.risk_multiplier(r)
                        * min(len(r.get("pairs") or []), self.lc.max_pairs_per_sleeve) for r in proven)
        if potential <= 0:
            return 1.0
        k = min(1.0, self.lc.proven_risk_budget / (concurrency * potential))
        if proven:
            self.reg.kv_set("proven_scale", {"scale": round(k, 3), "sleeves": len(proven),
                                             "potential_risk": round(potential, 4), "ts": iso()})
        return k

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
        pscale = self.proven_scale(rows)
        penalty = self.correlation_penalty([r["id"] for r in rows if r["stage"] in ("production", "incubation", "eligible")])
        # within a stage the strongest evidence gets its coins first (forward-proven, autopilot and
        # the owner's systems before plain research candidates), so a crowded coin (≤ 4 strategies)
        # or a full whitelist never leaves the best of them without anything to trade
        rows.sort(key=lambda r: (-STAGE_PRIORITY.get("incubation" if r["stage"] == "eligible" else r["stage"], 0),
                                 tuple(-x for x in self.evidence_rank(r))))
        # Pairs may be shared by up to `max_sleeves_per_pair` independent strategies (more
        # signals, more forward evidence); the whitelist is capped to protect the bot's memory.
        per_pair: dict[str, int] = {}
        union: set[str] = set()
        sleeves: list[Sleeve] = []
        for r in rows:
            mine: list[str] = []
            for p in r.get("pairs") or []:
                if p in excluded or per_pair.get(p, 0) >= self.lc.max_sleeves_per_pair:
                    continue
                if p not in union and len(union) >= self.lc.max_whitelist:
                    continue
                mine.append(p)
                if len(mine) >= self.lc.max_pairs_per_sleeve:
                    break
            if not mine:
                continue
            for p in mine:
                per_pair[p] = per_pair.get(p, 0) + 1
                union.add(p)
            stage = "incubation" if r["stage"] == "eligible" else r["stage"]
            sleeves.append(Sleeve(id=r["id"], family=r["family"], params=r["params"], pairs=mine,
                                  stage=stage,
                                  risk=round(self.risk_for(r["stage"]) * scale * penalty.get(r["id"], 1.0)
                                             * (self.risk_multiplier(r) * pscale
                                                if r["stage"] in ("production", "incubation", "eligible") else 1.0), 6),
                                  leverage=self.lc.leverage, sides=r.get("sides") or ["long", "short"],
                                  score=float(r.get("score") or 0.0), timeframe=self.strategy_tf(r)))
        # retired sleeves that still hold positions keep managing them (no new entries)
        live_ids = {s.id for s in sleeves}
        for t in open_trades:
            tag = t.get("enter_tag")
            if tag and tag not in live_ids:
                r = self.reg.one("SELECT * FROM strategies WHERE id=?", (tag,))
                if r:
                    sleeves.append(Sleeve(id=r["id"], family=r["family"], params=r["params"],
                                          pairs=[], stage="closing", risk=0.0, leverage=self.lc.leverage,
                                          sides=r.get("sides") or ["long", "short"], timeframe=self.strategy_tf(r)))
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
