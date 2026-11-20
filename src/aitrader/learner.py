"""Learning loop.

From **live** demo trades:
  * sync closed trades into the registry and attribute them to sleeves (enter_tag),
  * per-sleeve live metrics (used by the lifecycle manager for promotion/retirement),
  * failure analysis → concrete, testable adjustments:
      - pairs that keep losing are excluded for a while,
      - "winners turned into losers" (high MFE before stop) → earlier trailing,
      - time exits dominate with ~0 PnL → shorter holding window,
      - one side (long/short) persistently losing → research that family one-sided.
From **research** results:
  * which validation gates a family keeps failing → search-space/universe adjustments.
Every adjustment is A/B-tested by the generator and deactivated if it doesn't help.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

import numpy as np

from aitrader.registry import Registry
from aitrader.research.metrics import max_drawdown_from_pnl, profit_factor
from aitrader.settings import Settings
from aitrader.util import iso, utcnow

log = logging.getLogger(__name__)


def _lid(*parts: str) -> str:
    return "L" + hashlib.sha1("|".join(parts).encode()).hexdigest()[:10]


def live_metrics(trades: list[dict], equity: float) -> dict:
    if not trades:
        return {"trades": 0}
    pnl = np.array([float(t.get("profit_abs") or 0) for t in trades])
    ratios = np.array([float(t.get("profit_ratio") or 0) for t in trades])
    pf = profit_factor(pnl)
    return {
        "trades": len(trades),
        "pnl": round(float(pnl.sum()), 2),
        "profit_factor": round(pf, 3) if np.isfinite(pf) else 99.0,
        "win_rate": round(float((pnl > 0).mean()), 3),
        "expectancy": round(float(ratios.mean()), 5),
        "max_drawdown": round(max_drawdown_from_pnl(pnl, max(equity, 1.0)), 4),
        "first": trades[0].get("close_date"),
        "last": trades[-1].get("close_date"),
    }


def mfe_r(t: dict) -> float | None:
    """Max favourable excursion in R (initial risk) units."""
    try:
        o, sl = float(t["open_rate"]), float(t.get("initial_stop_loss_abs") or 0)
        r = abs(o - sl)
        if r <= 0:
            return None
        best = float(t["min_rate"]) if t.get("is_short") else float(t["max_rate"])
        return (o - best) / r if t.get("is_short") else (best - o) / r
    except (KeyError, TypeError, ValueError):
        return None


class Learner:
    def __init__(self, settings: Settings, registry: Registry):
        self.s = settings
        self.reg = registry

    # ------------------------------------------------------------------ live trades
    def sync_trades(self, trades: list[dict]) -> int:
        known = {r["trade_id"] for r in self.reg.q("SELECT trade_id FROM live_trades")}
        n = 0
        for t in trades:
            tid = t.get("trade_id")
            if tid is None or tid in known or t.get("is_open"):
                continue
            if (t.get("enter_tag") or "").startswith("exec-test"):
                continue  # execution self-test trades are not strategy evidence
            self.reg.upsert("live_trades", {
                "trade_id": tid, "sleeve_id": t.get("enter_tag") or "", "pair": t.get("pair"),
                "is_short": int(bool(t.get("is_short"))), "open_date": t.get("open_date"),
                "close_date": t.get("close_date"), "open_rate": t.get("open_rate"),
                "close_rate": t.get("close_rate"), "profit_ratio": t.get("profit_ratio"),
                "profit_abs": t.get("profit_abs"), "exit_reason": t.get("exit_reason"),
                "max_rate": t.get("max_rate"), "min_rate": t.get("min_rate"),
                "leverage": t.get("leverage"), "stake_amount": t.get("stake_amount"), "raw": t,
            }, key="trade_id")
            n += 1
        if n:
            self.reg.event("learner", f"synced {n} new closed demo trades")
        return n

    def trades_for(self, sleeve_id: str) -> list[dict]:
        return self.reg.q("SELECT * FROM live_trades WHERE sleeve_id=? ORDER BY close_date", (sleeve_id,))

    def _add(self, scope: str, key: str, insight: str, adjustment: dict, days: int = 30) -> None:
        lid = _lid(scope, key, str(sorted(adjustment.items())))
        if self.reg.one("SELECT id FROM learnings WHERE id=?", (lid,)):
            return
        self.reg.upsert("learnings", {
            "id": lid, "ts": iso(), "scope": scope, "key": key, "insight": insight,
            "adjustment": adjustment, "active": 1,
            "expires": iso(utcnow() + timedelta(days=days)),
        })
        self.reg.event("learner", f"new learning [{scope}:{key}] {insight}")

    def analyze_live(self) -> None:
        rows = self.reg.q("SELECT raw, sleeve_id, pair, profit_abs, exit_reason, is_short FROM live_trades")
        if not rows:
            return
        fam_of = {r["id"]: r["family"] for r in self.reg.q("SELECT id, family FROM strategies")}
        # 1) persistently losing pairs
        by_pair: dict[str, list[float]] = {}
        for r in rows:
            by_pair.setdefault(r["pair"], []).append(float(r["profit_abs"] or 0))
        for pair, pnl in by_pair.items():
            if len(pnl) >= 6 and profit_factor(np.array(pnl)) < 0.5:
                self._add("pair", pair, f"{pair}: {len(pnl)} demo trades, PF < 0.5 → excluded for 21 days",
                          {"exclude_pair": pair}, days=21)
        # 2) per-family exit analysis
        by_fam: dict[str, list[dict]] = {}
        for r in rows:
            fam = fam_of.get(r["sleeve_id"]) or (r["sleeve_id"].split("-")[1] if r["sleeve_id"].startswith("boot-") else None)
            if fam:
                by_fam.setdefault(fam, []).append(r)
        for fam, rs in by_fam.items():
            if len(rs) < 15:
                continue
            losers = [r for r in rs if float(r["profit_abs"] or 0) < 0]
            mfes = [m for m in (mfe_r(r["raw"]) for r in losers if isinstance(r.get("raw"), dict)) if m is not None]
            if len(mfes) >= 6 and np.mean(np.array(mfes) >= 1.0) >= 0.4:
                self._add("family", fam, f"{fam}: {np.mean(np.array(mfes) >= 1.0):.0%} of losing trades were "
                          "≥1R in profit first → test earlier trailing / closer targets",
                          {"space": {"trail_rr": [0.5, 1.5], "tp_rr": [1.0, 3.0]}})
            time_exits = [r for r in rs if r["exit_reason"] == "time_exit"]
            if len(time_exits) / len(rs) > 0.4 and abs(np.mean([float(r["profit_abs"] or 0) for r in time_exits])) < 1.0:
                self._add("family", fam, f"{fam}: {len(time_exits) / len(rs):.0%} of trades end by time "
                          "with ~0 PnL → test shorter holding windows",
                          {"space": {"max_hold": [12, 72]}})
            shorts = np.array([float(r["profit_abs"] or 0) for r in rs if r["is_short"]])
            longs = np.array([float(r["profit_abs"] or 0) for r in rs if not r["is_short"]])
            if len(shorts) >= 10 and len(longs) >= 10:
                if profit_factor(shorts) < 0.7 and profit_factor(longs) > 1.1:
                    self._add("family", fam, f"{fam}: shorts PF {profit_factor(shorts):.2f} vs longs "
                              f"{profit_factor(longs):.2f} → test long-only variant", {"sides": ["long"]})
                elif profit_factor(longs) < 0.7 and profit_factor(shorts) > 1.1:
                    self._add("family", fam, f"{fam}: longs PF {profit_factor(longs):.2f} vs shorts "
                              f"{profit_factor(shorts):.2f} → test short-only variant", {"sides": ["short"]})

    # ------------------------------------------------------------------ research
    def learn_from_research(self) -> None:
        rows = self.reg.q("SELECT family, result, spec FROM experiments WHERE status='done' "
                          "ORDER BY finished DESC LIMIT 60")
        by_fam: dict[str, list[dict]] = {}
        for r in rows:
            if isinstance(r.get("result"), dict):
                by_fam.setdefault(r["family"], []).append(r)
        for fam, rs in by_fam.items():
            recent = rs[:8]
            if len(recent) < 4:
                continue
            fails: dict[str, int] = {}
            for r in recent:
                for g, v in (r["result"].get("gates") or {}).items():
                    if not v.get("pass"):
                        fails[g] = fails.get(g, 0) + 1
            share = {g: n / len(recent) for g, n in fails.items()}
            if share.get("trades", 0) >= 0.5:
                self._add("research", fam, f"{fam}: too few OOS trades in {share['trades']:.0%} of recent "
                          "experiments → research on wider universes", {"extra_pairs": 4})
            if share.get("stress_pf", 0) >= 0.5 and share.get("profit_factor", 1) < 0.5:
                self._add("research", fam, f"{fam}: edge disappears under doubled costs → test longer holds "
                          "and larger targets", {"space": {"max_hold": [48, 168], "tp_rr": [2.0, 5.0]}})
            if share.get("max_drawdown", 0) >= 0.5:
                self._add("research", fam, f"{fam}: drawdown gate fails often → test tighter stops/earlier trailing",
                          {"space": {"sl_atr": [1.0, 2.5], "trail_rr": [0.5, 1.5]}})
        self.evaluate_learnings(rows)

    def evaluate_learnings(self, rows: list[dict]) -> None:
        """A/B: compare experiment scores with vs without each learning; prune losers."""
        for lr in self.reg.q("SELECT * FROM learnings WHERE active=1 AND scope IN ('family','research')"):
            fam = lr["key"]
            with_, without = [], []
            for r in rows:
                if r["family"] != fam or not isinstance(r.get("spec"), dict):
                    continue
                sc = float(r["result"].get("score", 0.0)) if isinstance(r.get("result"), dict) else 0.0
                (with_ if lr["id"] in r["spec"].get("used_learnings", []) else without).append(sc)
            if len(with_) >= 3 and len(without) >= 3:
                gain = float(np.mean(with_) - np.mean(without))
                adj = dict(lr.get("adjustment") or {})
                adj["ab"] = {"with": round(float(np.mean(with_)), 4), "without": round(float(np.mean(without)), 4),
                             "n": [len(with_), len(without)]}
                fields = {"adjustment": adj}
                if gain <= 0:
                    fields["active"] = 0
                    self.reg.event("learner", f"learning {lr['id']} deactivated (A/B gain {gain:+.3f})")
                self.reg.update("learnings", lr["id"], fields)
