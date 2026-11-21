"""One research experiment end-to-end:

  download data → for each walk-forward fold: hyperopt on train window, backtest the
  winner on the unseen test window (live strategy code path, realistic costs)
  → stressed-cost re-test → parameter-perturbation robustness → Monte-Carlo bootstrap
  → Deflated Sharpe → gates → candidate record in the registry.
"""

from __future__ import annotations

import logging
import random
import statistics
from datetime import timedelta

import numpy as np
import pandas as pd

from aitrader.families import MARKET_PAIR, NEEDS_MARKET, NEEDS_OI, RESEARCH_CLASS, get_family
from aitrader.manifest import Manifest, Sleeve
from aitrader.registry import Registry
from aitrader.research import metrics as M
from aitrader.research.ftrunner import FreqtradeRunner, Job, research_config
from aitrader.research.results import (
    best_epochs,
    epoch_sharpes,
    load_backtest,
    load_hyperopt_epochs,
    strategy_stats,
)
from aitrader.research.validation import (
    evaluate_gates,
    score,
    walk_forward_efficiency,
    walk_forward_folds,
)
from aitrader.settings import Settings
from aitrader.util import iso, utcnow, write_json_atomic

log = logging.getLogger(__name__)
STARTING_BALANCE = 10000.0


class Pipeline:
    def __init__(self, settings: Settings, registry: Registry, runner: FreqtradeRunner | None = None,
                 on_progress=None):
        self.s = settings
        self.reg = registry
        self.ft = runner or FreqtradeRunner(settings)
        self.on_progress = on_progress  # callback(eid, stage, extra) – research-lab live progress

    # ------------------------------------------------------------------ helpers
    def _progress(self, eid: str, stage: str, **extra) -> None:
        self.reg.update("experiments", eid, {"progress": {"stage": stage, "ts": iso(), **extra}})
        self.reg.heartbeat("research", "busy", {"experiment": eid, "stage": stage})
        if self.on_progress:
            try:
                self.on_progress(eid, stage, extra)
            except Exception:  # noqa: BLE001 – progress reporting must never break research
                log.debug("progress callback failed", exc_info=True)

    def _portfolio_backtest(self, job: Job, base_cfg, family: str, params: dict, pairs: list[str],
                            sides: list[str], timerange: str, fee: float, tag: str) -> list[dict]:
        man = Manifest(sleeves=[Sleeve(id=f"bt-{tag}", family=family, params=params, pairs=pairs,
                                       stage="production", risk=0.01,
                                       leverage=self.s.lifecycle.leverage, sides=sides)])
        mpath = job.path(f"manifest_{tag}.json")
        write_json_atomic(mpath, man.to_dict())
        overlay = self.ft.write_config(job, f"overlay_{tag}.json",
                                       {"aitrader": {"manifest_path": str(mpath)}})
        out = self.ft.backtest(job, [base_cfg, overlay], "AIPortfolio", timerange, fee, f"bt_{tag}")
        stats = strategy_stats(load_backtest(out), "AIPortfolio")
        return stats.get("trades", [])

    def _n_trials_and_var(self) -> tuple[int, float]:
        rows = self.reg.q("SELECT result FROM experiments WHERE status='done'")
        # a zero-trade experiment has no daily Sharpe – it is still a trial (Sharpe 0)
        srs = [float((r["result"].get("oos") or {}).get("daily_sharpe", 0.0)) for r in rows
               if isinstance(r.get("result"), dict) and "oos" in r["result"]]
        n = len(srs) + 1
        var = statistics.pvariance(srs) if len(srs) >= 5 else 1.0 / 365.0
        return n, max(var, 1e-6)

    # ------------------------------------------------------------------ main
    def run(self, eid: str, spec: dict) -> dict:
        rs = self.s.research
        fam = get_family(spec["family"])
        pairs: list[str] = spec["pairs"]
        sides: list[str] = spec.get("sides", ["long", "short"])
        seed = int(spec.get("seed", 42))
        job = Job(self.s.jobs_dir / eid)
        job.root.mkdir(parents=True, exist_ok=True)

        folds = walk_forward_folds(utcnow(), rs.train_days, rs.holdout_days, rs.wf_folds)
        tf = spec.get("timeframe") or rs.timeframe
        base_cfg = self.ft.write_config(job, "config.json",
                                        research_config(self.s, pairs, timeframe=tf, sides=sides))
        space_file = None
        if spec.get("space_overrides"):
            space_file = job.path("space.json")
            write_json_atomic(space_file, {fam.name: spec["space_overrides"]})

        # 1) data -----------------------------------------------------------
        self._progress(eid, "download")
        data_start = folds[0].train_start - timedelta(days=35)  # + 720-candle indicator warm-up
        data_pairs = sorted(set(pairs) | ({MARKET_PAIR} if fam.name in NEEDS_MARKET else set()))
        if tf == rs.timeframe:
            self.ft.download(job, base_cfg, data_pairs, f"{data_start:%Y%m%d}-")
        else:
            self.ft.download(job, base_cfg, data_pairs, f"{data_start:%Y%m%d}-", timeframe=tf)
        if fam.name in NEEDS_OI:  # open-interest history (Bybit only; the family is silent without it)
            from aitrader import oi as oimod
            oimod.download(self.s.market_data_dir, pairs, tf, data_start, rs.relay, rs.relay_token)

        # 2) walk-forward ---------------------------------------------------
        oos_trades, stress_trades, fold_reports, all_sharpes = [], [], [], []
        params = fam.defaults()
        is_annual = []
        fixed = spec.get("fixed_params")
        for k, fold in enumerate(folds):
            self._progress(eid, f"hyperopt fold {k + 1}/{len(folds)}", fold=fold.train_range)
            if fixed:  # a given configuration (e.g. the owner's): no search, just the honest test
                params = fam.normalize(fixed)
                tr_is = self._portfolio_backtest(job, base_cfg, fam.name, params, pairs, sides,
                                                 fold.train_range, rs.base_fee, f"is{k}")
                ism_s = M.summarize(tr_is, STARTING_BALANCE, fold.train_start, fold.train_end)
                ism = {"total_trades": ism_s["trades"], "profit_total": ism_s["total_return"]}
                all_sharpes.append(float(ism_s.get("sharpe") or 0.0))
            else:
                hdir = self.ft.hyperopt(job, [base_cfg], RESEARCH_CLASS[fam.name], fold.train_range,
                                        int(spec.get("epochs", rs.epochs)), rs.base_fee, seed + k,
                                        min_trades=20, space_file=space_file)
                epochs = load_hyperopt_epochs(hdir)
                all_sharpes += epoch_sharpes(epochs)
                best = best_epochs(epochs, min_trades=20, top=1)
                if not best:
                    fold_reports.append({"fold": k, "error": "no epoch with enough trades"})
                    continue
                pins = {k: v[0] for k, v in (spec.get("space_overrides") or {}).items()
                        if isinstance(v, (list, tuple)) and len(v) == 2 and v[0] == v[1]}
                params = fam.normalize({**best[0]["params_dict"], **pins})
                ism = best[0].get("results_metrics", {})
            train_days = (fold.train_end - fold.train_start).days
            is_ann = (1 + float(ism.get("profit_total", 0.0))) ** (365 / max(train_days, 1)) - 1
            is_annual.append(is_ann)

            self._progress(eid, f"oos fold {k + 1}/{len(folds)}", fold=fold.test_range)
            tr = self._portfolio_backtest(job, base_cfg, fam.name, params, pairs, sides,
                                          fold.test_range, rs.base_fee, f"oos{k}")
            st = self._portfolio_backtest(job, base_cfg, fam.name, params, pairs, sides,
                                          fold.test_range, rs.stress_fee, f"stress{k}")
            oos_trades += tr
            stress_trades += st
            fold_reports.append({
                "fold": k, "train": fold.train_range, "test": fold.test_range, "params": params,
                "is_trades": ism.get("total_trades"), "is_profit": ism.get("profit_total"),
                "is_annual": round(is_ann, 4),
                "oos": M.summarize(tr, STARTING_BALANCE, fold.test_start, fold.test_end),
            })

        oos_start, oos_end = folds[0].test_start, folds[-1].test_end
        oos = M.summarize(oos_trades, STARTING_BALANCE, oos_start, oos_end)
        stress = M.summarize(stress_trades, STARTING_BALANCE, oos_start, oos_end)

        # 3) robustness: perturb final params on the last test window ----------
        self._progress(eid, "robustness")
        rng = random.Random(seed)
        last = folds[-1]
        pert_pfs, pert_profitable = [], 0
        if oos["trades"] > 0:
            for i in range(rs.perturbations):
                pp = fam.perturb(params, 0.10, rng)
                tr = self._portfolio_backtest(job, base_cfg, fam.name, pp, pairs, sides,
                                              last.test_range, rs.base_fee, f"pert{i}")
                sm = M.summarize(tr, STARTING_BALANCE, last.test_start, last.test_end)
                pert_pfs.append(sm["profit_factor"])
                pert_profitable += int(sm["total_return"] > 0)
        robust_frac = pert_profitable / rs.perturbations if pert_pfs else 0.0

        # 4) Monte Carlo + deflated Sharpe --------------------------------------
        pnl = np.array([float(t.get("profit_abs", 0.0)) for t in oos_trades])
        mc = M.monte_carlo(pnl, STARTING_BALANCE, rs.mc_samples, seed)
        n_trials, sr_var = self._n_trials_and_var()
        dsr = M.deflated_sharpe(oos.get("daily_sharpe", 0.0), oos.get("n_days", 0), n_trials,
                                sr_var, oos.get("skew", 0.0), oos.get("kurtosis", 3.0))
        wfe = walk_forward_efficiency(float(np.mean(is_annual)) if is_annual else 0.0,
                                      oos.get("annual_return", 0.0))

        fold_pos = (sum(1 for f in fold_reports if (f.get("oos") or {}).get("total_return", 0) > 0)
                    / max(len(folds), 1))
        verdict, gates = evaluate_gates(self.s.gates, {
            "oos": oos, "stress": stress, "wfe": wfe, "robust_frac": robust_frac, "mc": mc,
            "dsr": dsr, "fold_pos": fold_pos})

        # 5) per-pair attribution → which pairs this strategy should own --------
        df = M.trades_frame(oos_trades)
        pair_stats = {}
        if not df.empty:
            g = df.groupby("pair")["profit_abs"].agg(["sum", "count"])
            pair_stats = {p: {"pnl": round(float(r["sum"]), 2), "trades": int(r["count"])}
                          for p, r in g.iterrows()}
        good_pairs = [p for p, v in sorted(pair_stats.items(), key=lambda kv: -kv[1]["pnl"])
                      if v["pnl"] > 0][: self.s.lifecycle.max_pairs_per_sleeve]

        result = {
            "verdict": verdict, "gates": gates, "oos": oos, "stress": stress, "mc": mc,
            "dsr": round(dsr, 4), "n_trials": n_trials, "wfe": round(wfe, 4),
            "robust_frac": round(robust_frac, 3), "fold_pos": round(fold_pos, 3),
            "perturb_pf_median": round(float(np.median(pert_pfs)), 3) if pert_pfs else 0.0,
            "folds": fold_reports, "params": params, "pairs": good_pairs, "variant": fam.variant(params),
            "pair_stats": pair_stats, "score": score(oos, dsr), "timeframe": tf,
            "epoch_sharpe_std": round(float(np.std(all_sharpes)), 4) if all_sharpes else None,
            "exit_reasons": (df["exit_reason"].value_counts().to_dict() if not df.empty else {}),
            "curve": M.equity_curve(oos_trades, STARTING_BALANCE, oos_start, oos_end),
        }
        self._record_strategy(eid, spec, result)
        return result

    def _record_strategy(self, eid: str, spec: dict, result: dict) -> None:
        stage = {"validated": "validated", "exploratory": "exploratory"}.get(
            result["verdict"], "rejected")
        if stage != "rejected" and not result["pairs"]:
            stage = "rejected"
        sid = f"{spec['family'][:5]}-{eid[1:7]}"
        now = iso()
        self.reg.upsert("strategies", {
            "id": sid, "experiment_id": eid, "family": spec["family"],
            "params": result["params"], "pairs": result["pairs"],
            "sides": spec.get("sides", ["long", "short"]), "stage": stage,
            "score": result["score"], "oos": {**result["oos"], "mc": result["mc"], "dsr": result["dsr"],
                                              "wfe": result["wfe"], "variant": result["variant"]},
            "gates": result["gates"], "live": {}, "created": now, "updated": now,
            "stage_since": now, "history": [{"ts": now, "to": stage, "reason": "research"}],
            "note": f"universe={len(spec['pairs'])} pairs",
        })
        self.reg.event("research", f"{sid} ({result['variant']}): {stage} — OOS trades "
                       f"{result['oos']['trades']}, PF {result['oos']['profit_factor']}, "
                       f"Sharpe {result['oos']['sharpe']}, DD {result['oos']['max_drawdown']}",
                       data={"strategy": sid, "experiment": eid})


def pair_file(settings: Settings, pair: str):
    base = pair
    for ch in ["/", " ", ".", "@", "$", "+", ":"]:
        base = base.replace(ch, "_")
    return settings.market_data_dir / "futures" / f"{base}-{settings.research.timeframe}-futures.feather"


def pairs_with_history(settings: Settings, pairs: list[str], min_days: int) -> list[str]:
    """Keep pairs whose local 1h futures data spans at least `min_days`."""
    ok = []
    for p in pairs:
        fn = pair_file(settings, p)
        if not fn.exists():
            continue
        try:
            d = pd.read_feather(fn, columns=["date"])["date"]
            if (d.max() - d.min()).days >= min_days:
                ok.append(p)
        except Exception:  # noqa: BLE001
            continue
    return ok
