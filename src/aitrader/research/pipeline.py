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
    clean_oos,
    evaluate_gates,
    score,
    walk_forward_efficiency,
    walk_forward_folds,
)
from aitrader.settings import Settings
from aitrader.util import iso, utcnow, write_json_atomic

log = logging.getLogger(__name__)
STARTING_BALANCE = 10000.0



LONG_REPLICATION_TF = ("2h", "4h", "6h", "12h")


def _pf(trades: list[dict]) -> float | None:
    win = sum(float(t.get("profit_abs") or 0.0) for t in trades if float(t.get("profit_abs") or 0.0) > 0)
    loss = -sum(float(t.get("profit_abs") or 0.0) for t in trades if float(t.get("profit_abs") or 0.0) < 0)
    if not trades:
        return None
    return round(win / loss, 3) if loss > 0 else None


PARITY_SIGNAL_BAND = (0.75, 1.33)  # bot trades / engine trades (same coin, same length of time)


def parity(spec: dict, oos: dict, trades: list[dict] | None = None, days: int | None = None) -> dict | None:
    """Does the bot reproduce what the owner's engine saw – like for like?

    The engine's record (A: the search years, B: the last 90 days) is for ONE coin, the one the
    configuration was found on (`screen_holdout.coins.list[0]`). Until 2026-11-22 it was
    compared with the bot's result on all coins of the configuration, so coins added by the
    screener's "also holds elsewhere" check made a faithful replication look broken (first
    3-year run: 11 of 15 "broken", while trade counts on the primary coin matched 65/66,
    36/36, 51/51). Now, on the primary coin only:
      * signals – the bot's trade count against the engine's trade rate over the same length
        of time (within 0.75–1.33×; checked from 10 expected trades);
      * money – engine PF ≥ 1.3 but bot PF < 1.0 with ≥ 10 trades is a gap.
    The other coins are reported apart (`others`): how the configuration transfers, not parity."""
    sh = spec.get("screen_holdout") or {}
    a = sh.get("A") or None
    if not a or a.get("pf") is None:
        return None
    e_pf = float(a["pf"])
    primary = ((sh.get("coins") or {}).get("list") or [None])[0]
    if trades is None or not primary:  # no trade detail: the old pooled comparison, marked as such
        b_pf, n = float(oos.get("profit_factor") or 0.0), int(oos.get("trades") or 0)
        broken = e_pf >= 1.3 and n >= 10 and b_pf < 1.0
        return {"engine_pf": round(e_pf, 3), "engine_trades": a.get("trades"), "bot_pf": round(b_pf, 3),
                "bot_trades": n, "pooled": True, "ok": not broken}
    mine = [t for t in trades if t.get("pair") == primary]
    rest = [t for t in trades if t.get("pair") != primary]
    n, b_pf = len(mine), _pf(mine)
    b = sh.get("B") or {}
    e_days = float(a.get("years") or 0.0) * 365.0 + (90.0 if b else 0.0)
    e_trades = int(a.get("trades") or 0) + int(b.get("trades") or 0)
    expected = None
    if e_days > 0 and days:
        expected = round(e_trades / e_days * min(float(days), e_days), 1)
    lo, hi = PARITY_SIGNAL_BAND
    signals_ok = expected is None or expected < 10 or lo <= n / expected <= hi
    profit_ok = not (e_pf >= 1.3 and n >= 10 and (b_pf if b_pf is not None else 0.0) < 1.0)
    return {"coin": primary, "engine_pf": round(e_pf, 3), "engine_trades": a.get("trades"),
            "expected_trades": expected, "bot_pf": b_pf, "bot_trades": n,
            "signals_ok": bool(signals_ok), "profit_ok": bool(profit_ok), "ok": bool(signals_ok and profit_ok),
            "others": {"coins": len({t.get("pair") for t in rest}), "trades": len(rest), "pf": _pf(rest),
                       "pnl": round(sum(float(t.get("profit_abs") or 0.0) for t in rest), 2)}}

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

        tf = spec.get("timeframe") or rs.timeframe
        long_rep = bool(spec.get("fixed_params")) and tf in LONG_REPLICATION_TF
        folds = (walk_forward_folds(utcnow(), rs.replication_train_days, rs.replication_days, rs.replication_folds)
                 if long_rep else walk_forward_folds(utcnow(), rs.train_days, rs.holdout_days, rs.wf_folds))
        base_cfg = self.ft.write_config(job, "config.json",
                                        research_config(self.s, pairs, timeframe=tf, sides=sides))
        space_file = None
        if spec.get("space_overrides"):
            space_file = job.path("space.json")
            write_json_atomic(space_file, {fam.name: spec["space_overrides"]})

        # 1) data -----------------------------------------------------------
        self._progress(eid, "download")
        from aitrader.research.screen import warmup_days
        data_start = folds[0].train_start - timedelta(days=warmup_days(tf))  # + 720-candle indicator warm-up
        data_pairs = sorted(set(pairs) | ({MARKET_PAIR} if fam.name in NEEDS_MARKET else set()))
        if tf == rs.timeframe:
            self.ft.download(job, base_cfg, data_pairs, f"{data_start:%Y%m%d}-")
        else:
            self.ft.download(job, base_cfg, data_pairs, f"{data_start:%Y%m%d}-", timeframe=tf)
        if long_rep:
            # older candles than the cache holds, then fit the quarters to what really exists
            try:
                self.ft.download(job, base_cfg, data_pairs, f"{data_start:%Y%m%d}-", timeframe=tf, prepend=True)
            except Exception as e:  # noqa: BLE001 – older history is a bonus; fit_folds copes without it
                log.warning("%s: prepending older candles failed: %s", eid, str(e)[:200])
            first = earliest_candle(self.s, pairs, tf)
            n = fit_folds(first, warmup_days(tf), rs.replication_train_days, rs.replication_folds)
            if n < len(folds):
                log.info("%s: history from %s fits %d of %d replication quarters", eid, first, n, len(folds))
                folds = walk_forward_folds(utcnow(), rs.replication_train_days, 90 * n, n)
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
        clean = clean_oos(spec)
        market = self._oos_market_split(oos_trades, oos_start, oos_end)
        verdict, gates = evaluate_gates(self.s.gates, {
            "oos": oos, "stress": stress, "wfe": wfe, "robust_frac": robust_frac, "mc": mc,
            "dsr": dsr, "fold_pos": fold_pos, "clean_oos": clean,
            "alpha": (market or {}).get("alpha"), "alpha_t": (market or {}).get("alpha_t")})

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
            "dsr": round(dsr, 4), "n_trials": n_trials, "wfe": round(wfe, 4), "clean_oos": clean, "market": market,
            "robust_frac": round(robust_frac, 3), "fold_pos": round(fold_pos, 3),
            "perturb_pf_median": round(float(np.median(pert_pfs)), 3) if pert_pfs else 0.0,
            "folds": fold_reports, "params": params, "pairs": good_pairs, "variant": fam.variant(params),
            "pair_stats": pair_stats, "score": score(oos, dsr), "timeframe": tf,
            "epoch_sharpe_std": round(float(np.std(all_sharpes)), 4) if all_sharpes else None,
            "exit_reasons": (df["exit_reason"].value_counts().to_dict() if not df.empty else {}),
            "curve": M.equity_curve(oos_trades, STARTING_BALANCE, oos_start, oos_end),
            "replication": {"days": (oos_end - oos_start).days, "folds": len(folds)} if long_rep else None,
            "parity": parity(spec, oos, oos_trades, (oos_end - oos_start).days),
        }
        self._record_strategy(eid, spec, result)
        return result

    def _oos_market_split(self, trades: list[dict], start, end) -> dict | None:
        """Beta to BTC and the alpha left after it, on the walk-forward OOS daily P&L. None
        when BTC candles are not in the local data (the gate is then simply not applied)."""
        from aitrader import evidence as EV
        try:
            fn = pair_file(self.s, MARKET_PAIR)
            if not trades or not fn.exists():
                return None
            d = pd.read_feather(fn, columns=["date", "close"])
            d = d[(d["date"] >= pd.Timestamp(start)) & (d["date"] <= pd.Timestamp(end))]
            closes = d.set_index("date")["close"].resample("1D").last().dropna()
            btc = np.log(closes).diff().dropna()
            y = EV.daily_returns(trades, STARTING_BALANCE, lambda t: float(t.get("profit_abs") or 0.0), end=end)
            ab = EV.alpha_beta(y, btc, min_days=30)
            if ab.get("alpha") is None:
                return None
            return {"alpha": ab["alpha"], "alpha_ann": ab["alpha_ann"], "beta": ab["beta"], "alpha_t": ab["alpha_t"],
                    "days": ab["days"]}
        except Exception as e:  # noqa: BLE001 – a missing/odd file must not fail the experiment
            log.info("OOS market split unavailable: %s", e)
            return None

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


def pair_file(settings: Settings, pair: str, tf: str | None = None):
    base = pair
    for ch in ["/", " ", ".", "@", "$", "+", ":"]:
        base = base.replace(ch, "_")
    return settings.market_data_dir / "futures" / f"{base}-{tf or settings.research.timeframe}-futures.feather"


def earliest_candle(settings: Settings, pairs: list[str], tf: str):
    """First candle of the pair with the longest local history (None if nothing is there)."""
    import pandas as pd
    firsts = []
    for p in pairs:
        f = pair_file(settings, p, tf)
        if not f.exists():
            continue
        try:
            d = pd.read_feather(f, columns=["date"])["date"]
        except Exception:  # noqa: BLE001 – unreadable file: treat as missing
            continue
        if len(d):
            firsts.append(pd.Timestamp(d.min()).to_pydatetime())
    return min(firsts) if firsts else None


def fit_folds(first, warmup: int, train: int, want: int, now=None, quarter: int = 90) -> int:
    """How many 90-day replication quarters fit after `first` + warm-up + training (4..want)."""
    if first is None:
        return 4
    now = now or utcnow()
    if first.tzinfo is None:
        from datetime import UTC
        first = first.replace(tzinfo=UTC)
    room = (now - first).days - warmup - train - 2
    return max(4, min(want, room // quarter))


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
