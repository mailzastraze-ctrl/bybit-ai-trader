"""Offline bulk research (GitHub Actions or any machine with Freqtrade).

  python -m aitrader.research.batch scan  --out DIR
  python -m aitrader.research.batch run   --out DIR --job K --experiments N
  python -m aitrader.research.batch merge --out FILE --report MD --batch-id ID DIR [DIR ...]

`merge` recomputes the Deflated Sharpe Ratio with the number of trials across the WHOLE
batch (all parallel jobs), re-applies the gates and writes an import file. The live system
imports it on start (lifecycle.import_offline_candidates); imported strategies still have
to pass forward testing on Bybit Demo before they get production risk.
"""

from __future__ import annotations

import argparse
import json
import statistics
import traceback
from pathlib import Path

from aitrader.families import FAMILIES
from aitrader.registry import Registry
from aitrader.research import metrics as M
from aitrader.research.generator import Generator
from aitrader.research.pipeline import Pipeline
from aitrader.research.validation import evaluate_gates, score
from aitrader.settings import get_settings
from aitrader.util import iso, setup_logging, write_json_atomic

log = setup_logging("batch")


def cmd_scan(out: Path, reg: Registry | None = None) -> None:
    from aitrader.scanner import Scanner
    s = get_settings()
    s.ensure_dirs()
    reg = reg or Registry(out / "scan.sqlite")
    pairs = Scanner(s, reg).refresh()
    market = {r["pair"]: r["data"] for r in reg.q("SELECT pair, data FROM market")}
    write_json_atomic(out / "universe.json", {"ts": iso(), "exchange": s.research.exchange,
                                              "pairs": pairs, "market": market})
    log.info("universe: %d pairs", len(pairs))


def cmd_run(out: Path, job: int, n: int, universe_file: Path) -> None:
    s = get_settings()
    s.ensure_dirs()
    uni = json.loads(universe_file.read_text())
    reg = Registry(out / f"registry-{job}.sqlite")
    for p, d in uni.get("market", {}).items():
        reg.upsert("market", {"pair": p, "ts": uni["ts"], "data": d}, key="pair")
    gen = Generator(s, reg, seed=1000 + job)
    pipe = Pipeline(s, reg)
    fams = list(FAMILIES)
    results = []
    for i in range(n):
        spec = gen.next_spec(uni["pairs"], family=fams[(job * n + i) % len(fams)])
        eid = reg.new_experiment(spec["family"], spec)
        log.info("job %d experiment %d/%d %s: %s", job, i + 1, n, eid, spec["family"])
        started = iso()
        try:
            res = pipe.run(eid, spec)
            results.append({"id": eid, "spec": spec, "result": res, "started": started, "finished": iso()})
        except Exception as e:  # noqa: BLE001
            log.error("experiment %s failed: %s", eid, e)
            results.append({"id": eid, "spec": spec, "error": f"{e}\n{traceback.format_exc()[-800:]}",
                            "started": started, "finished": iso()})
        write_json_atomic(out / f"results-{job}.json", {"job": job, "exchange": uni.get("exchange", s.research.exchange),
                                                        "experiments": results})


LEDGER_WINDOW_DAYS = 90
RESULT_KEYS = ("oos", "stress", "mc", "wfe", "robust_frac", "fold_pos", "perturb_pf_median", "params", "pairs",
               "variant", "pair_stats", "exit_reasons", "epoch_sharpe_std")


def ledger_trials(ledger: dict | None, now=None) -> list[float]:
    """Daily Sharpe ratios of every research trial in the last 90 days (all batches)."""
    from datetime import timedelta

    from aitrader.util import parse_dt, utcnow
    cutoff = (now or utcnow()) - timedelta(days=LEDGER_WINDOW_DAYS)
    out = []
    for t in (ledger or {}).get("trials", []):
        ts = parse_dt(t.get("ts"))
        if ts is not None and ts >= cutoff and t.get("sr") is not None:
            out.append(float(t["sr"]))
    return out


def update_ledger(ledger: dict | None, m: dict) -> dict:
    from datetime import timedelta

    from aitrader.util import parse_dt, utcnow
    keep_after = utcnow() - timedelta(days=365)
    trials = [t for t in (ledger or {}).get("trials", []) if (parse_dt(t.get("ts")) or keep_after) >= keep_after]
    for e in m["experiments_full"]:
        if e.get("result") and isinstance(e["result"].get("oos"), dict):
            trials.append({"id": e["id"], "ts": e.get("finished") or m["created"], "batch": m["batch_id"],
                           "family": e["spec"].get("family"), "sr": e["result"]["oos"].get("daily_sharpe", 0.0)})
    return {"note": "Every research trial (all batches). Deflated Sharpe counts trials of the last "
                    f"{LEDGER_WINDOW_DAYS} days, so repeated searching cannot inflate significance.",
            "trials": trials}


def merge(dirs: list[Path], batch_id: str, ledger: dict | None = None) -> dict:
    s = get_settings()
    exps, exchange = [], None
    for d in dirs:
        for f in sorted(Path(d).rglob("results-*.json")):
            data = json.loads(f.read_text())
            exchange = data.get("exchange", exchange)
            exps += data["experiments"]
    done = [e for e in exps if "result" in e]
    srs = ledger_trials(ledger) + [e["result"]["oos"].get("daily_sharpe", 0.0) for e in done]
    n_trials = max(len(srs), 1)
    var = statistics.pvariance(srs) if len(srs) >= 5 else 1.0 / 365.0
    candidates = []
    for idx, e in enumerate(done):
        r = e["result"]
        oos = r["oos"]
        dsr = M.deflated_sharpe(oos.get("daily_sharpe", 0.0), oos.get("n_days", 0), n_trials, max(var, 1e-6),
                                oos.get("skew", 0.0), oos.get("kurtosis", 3.0))
        verdict, gates = evaluate_gates(s.gates, {"oos": oos, "stress": r["stress"], "wfe": r["wfe"],
                                                  "robust_frac": r["robust_frac"], "mc": r["mc"], "dsr": dsr,
                                                  "fold_pos": r.get("fold_pos")})
        e["batch_verdict"], e["batch_dsr"], e["batch_gates"] = verdict, round(dsr, 4), gates
        if verdict != "rejected" and r.get("pairs"):
            candidates.append({
                "id": f"{batch_id}-{e['spec']['family'][:5]}-{idx:02d}",
                "family": e["spec"]["family"], "params": r["params"], "pairs": r["pairs"],
                "sides": e["spec"].get("sides", ["long", "short"]), "stage": verdict,
                "score": score(oos, dsr), "variant": r.get("variant", e["spec"]["family"]),
                "oos": {**oos, "mc": r["mc"], "dsr": round(dsr, 4), "wfe": r["wfe"],
                        "variant": r.get("variant", e["spec"]["family"])},
                "gates": gates, "experiment": e["id"],
            })
    candidates.sort(key=lambda c: -c["score"])
    full = []
    for e in exps:
        row = {"id": e["id"], "spec": e["spec"], "started": e.get("started"), "finished": e.get("finished")}
        if "result" in e:
            r = e["result"]
            row["result"] = {k: r.get(k) for k in RESULT_KEYS} | {
                "verdict": e["batch_verdict"], "gates": e["batch_gates"], "dsr": e["batch_dsr"],
                "n_trials": n_trials, "score": score(r["oos"], e["batch_dsr"]),
                "folds": [{k: f.get(k) for k in ("fold", "train", "test", "is_trades", "is_profit", "oos")}
                          for f in r.get("folds", [])]}
        else:
            row["error"] = str(e.get("error", ""))[:1500]
        full.append(row)
    return {"batch_id": batch_id, "created": iso(), "exchange": exchange, "n_experiments": len(exps),
            "n_completed": len(done), "n_trials_for_dsr": n_trials, "candidates": candidates,
            "experiments_full": full,
            "experiments": [{k: e.get(k) for k in ("id", "batch_verdict", "batch_dsr", "error")}
                            | {"family": e.get("result", {}).get("variant", e["spec"]["family"]), "pairs": e["spec"]["pairs"],
                               "oos": e.get("result", {}).get("oos"),
                               "gates": e.get("batch_gates")} for e in exps]}


def report_md(m: dict) -> str:
    lines = [f"# Research batch {m['batch_id']}", "",
             f"- Created: {m['created']} · data: **{m['exchange']}** USDT perps (1h) · "
             f"experiments: {m['n_completed']}/{m['n_experiments']} completed",
             f"- Deflated Sharpe uses N = {m['n_trials_for_dsr']} trials (whole batch).",
             f"- Candidates passing gates: **{len(m['candidates'])}** "
             f"({sum(c['stage'] == 'validated' for c in m['candidates'])} validated, "
             f"{sum(c['stage'] == 'exploratory' for c in m['candidates'])} exploratory)", "",
             "All metrics are walk-forward out-of-sample, after fees+slippage; stress = doubled costs. "
             "Imported strategies must still pass forward testing on Bybit Demo before production.", "",
             "| Experiment | Family | Verdict | OOS trades | PF | Sharpe | Max DD | DSR | Failed gates |",
             "|---|---|---|---:|---:|---:|---:|---:|---|"]
    for e in m["experiments"]:
        o = e.get("oos") or {}
        failed = ", ".join(k for k, g in (e.get("gates") or {}).items() if not g["pass"]) or ("error" if e.get("error") else "—")
        lines.append(f"| {e['id']} | {e['family']} | {e.get('batch_verdict') or 'error'} | {o.get('trades', '–')} | "
                     f"{o.get('profit_factor', '–')} | {o.get('sharpe', '–')} | {o.get('max_drawdown', '–')} | "
                     f"{e.get('batch_dsr', '–')} | {failed} |")
    if m["candidates"]:
        lines += ["", "## Candidates", ""]
        for c in m["candidates"]:
            lines.append(f"- **{c['id']}** ({c.get('variant', c['family'])}, {c['stage']}, score {c['score']}): pairs {', '.join(c['pairs'])}; "
                         f"params `{json.dumps(c['params'])}`")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------- research lab
class EpochWatcher:
    """Reports hyperopt epoch progress (epochs done, best loss so far) of the running
    experiment to the live server while freqtrade is busy."""

    def __init__(self, settings, lab, every: float = 25.0):
        import threading
        self.s, self.lab, self.every = settings, lab, every
        self.cur: dict = {}
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._t.start()
        return self

    def stop(self):
        self._stop.set()

    def snapshot(self, eid: str) -> dict | None:
        files = sorted((self.s.jobs_dir / eid).rglob("*.fthypt"), key=lambda f: f.stat().st_mtime)
        if not files:
            return None
        n, best = 0, None
        for line in files[-1].read_text(errors="ignore").splitlines():
            try:
                ep = json.loads(line)
            except json.JSONDecodeError:
                continue
            n += 1
            if best is None or float(ep.get("loss", 1e9)) < float(best.get("loss", 1e9)):
                best = ep
        out = {"epoch": n}
        if best:
            rm = best.get("results_metrics") or {}
            out.update(best_loss=round(float(best.get("loss", 0)), 4), best_trades=rm.get("total_trades"),
                       best_profit=round(float(rm.get("profit_total") or 0), 4))
        return out

    def _loop(self):
        while not self._stop.wait(self.every):
            cur = dict(self.cur)
            if not cur.get("eid") or not str(cur.get("stage", "")).startswith("hyperopt"):
                continue
            try:
                snap = self.snapshot(cur["eid"])
            except OSError:
                snap = None
            if snap:
                self.lab.progress(cur["eid"], cur["stage"], force=False, epochs=cur.get("epochs"), **snap)


def _fresh_universe(path: Path, max_age_h: float = 12) -> dict | None:
    from aitrader.util import parse_dt, utcnow
    if not path.exists():
        return None
    try:
        u = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    ts = parse_dt(u.get("ts"))
    if ts is None or (utcnow() - ts).total_seconds() > max_age_h * 3600 or len(u.get("pairs") or []) < 6:
        return None
    return u


def probe_bybit(relay: str, token: str) -> bool:
    import requests
    try:
        r = requests.get(relay + "https://api.bybit.com/v5/market/time", headers={"X-Lab-Token": token}, timeout=20)
        ok = r.status_code == 200 and r.json().get("retCode") == 0
        log.info("Bybit via EU relay: HTTP %s %s", r.status_code, "OK" if ok else r.text[:200])
        return ok
    except Exception as e:  # noqa: BLE001
        log.warning("Bybit via EU relay failed: %s", e)
        return False


def plan(gen: Generator, state: dict, pairs: list[str], rng):
    """Endless spec stream: revalidations first, then ~25% refinements of promising
    strategies and ~75% new searches chosen by the UCB bandit (+ A/B'd learnings)."""
    for st in state.get("revalidate", []):
        if st.get("family") in FAMILIES:
            spec = gen.next_spec(pairs, family=st["family"])
            own = [p for p in (st.get("pairs") or []) if p in pairs]
            spec["pairs"] = (own + [p for p in spec["pairs"] if p not in own])[:max(len(own), len(spec["pairs"]))]
            spec["revalidates"] = st["id"]
            yield spec
    pool = [c for c in state.get("refine", []) if c.get("family") in FAMILIES]
    while True:
        if pool and rng.random() < 0.25:
            yield gen.refine_spec(pairs, rng.choice(pool))
        else:
            yield gen.next_spec(pairs)


def cmd_cycle(out: Path, budget_min: float, run_id: str, server: str | None, max_exp: int,
              ledger_path: Path | None, export: Path) -> dict | None:
    import os
    import random
    import time

    from aitrader.research.labclient import LabClient
    s = get_settings()
    s.ensure_dirs()
    out.mkdir(parents=True, exist_ok=True)
    lab = LabClient(server, run_id)
    state = lab.state() if lab.enabled else {}
    log.info("lab state: %d learnings, %d revalidations due, %d refine candidates, family stats %s",
             len(state.get("learnings", [])), len(state.get("revalidate", [])), len(state.get("refine", [])),
             state.get("family_stats"))
    if state.get("paused"):
        log.warning("research paused from the terminal – nothing to do")
        return None
    public = os.environ.get("LAB_PUBLIC", "") == "true"
    # Real Bybit data: GitHub runners are geo-blocked by Bybit (US), so public market-data
    # requests go through the live server's relay (EU). Fallback: OKX data.
    relay = lab.relay() if lab.enabled else None
    if relay and probe_bybit(*relay):
        s.research.exchange, (s.research.relay, s.research.relay_token) = "bybit", relay
    else:
        log.warning("Bybit relay unavailable – researching on %s data", s.research.exchange)
    lab.run_event("start", budget_min=budget_min, cpus=os.cpu_count(), public=public,
                  exchange=s.research.exchange)

    db = out / "lab.sqlite"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    reg = Registry(db)
    for lr in state.get("learnings", []):
        reg.upsert("learnings", {k: lr.get(k) for k in ("id", "scope", "key", "insight", "adjustment", "expires")}
                   | {"ts": iso(), "active": 1})

    uni = _fresh_universe(out / "universe.json")
    if uni is not None and uni.get("exchange") != s.research.exchange:
        uni = None  # cached universe belongs to the other exchange
    if uni is None:
        cmd_scan(out, reg)
        uni = json.loads((out / "universe.json").read_text())
        lab.run_event("scan", exchange=uni.get("exchange"), pairs=uni.get("pairs"))
    if len(uni.get("pairs") or []) < 4 and s.research.exchange == "bybit":
        log.error("Bybit universe empty (%s) – falling back to OKX data for this run", uni.get("pairs"))
        lab.run_event("scan", exchange="bybit-failed", pairs=[])
        s.research.exchange, s.research.relay, s.research.relay_token = "okx", "", ""
        cmd_scan(out, reg)
        uni = json.loads((out / "universe.json").read_text())
    if len(uni.get("pairs") or []) < 4:
        log.error("universe too small (%s) – no experiments this run", uni.get("pairs"))
        lab.run_event("end", experiments=0, error="universe too small")
        return None
    for p, d in uni.get("market", {}).items():
        reg.upsert("market", {"pair": p, "ts": uni["ts"], "data": d}, key="pair")
    pairs = uni["pairs"]

    seed = int("".join(ch for ch in run_id if ch.isdigit())[-6:] or 0)
    gen = Generator(s, reg, seed=seed, stats_override=state.get("family_stats"))
    watcher = EpochWatcher(s, lab).start()

    def on_progress(eid, stage, extra):
        watcher.cur.update(eid=eid, stage=stage)
        left = budget_min - (time.time() - t0) / 60
        lab.progress(eid, stage, fold=extra.get("fold"), epochs=watcher.cur.get("epochs"),
                     budget_left_min=round(left, 1))

    pipe = Pipeline(s, reg, on_progress=on_progress)
    specs = plan(gen, state, pairs, random.Random(seed))
    jdir = out / "job-lab"
    jdir.mkdir(exist_ok=True)
    for f in jdir.glob("results-*.json"):
        f.unlink()
    t0, durations, results = time.time(), [], []
    while len(results) < max_exp:
        elapsed = (time.time() - t0) / 60
        est = statistics.median(durations) if durations else 18.0
        if elapsed + est > budget_min:
            log.info("budget: %.0f of %.0f min used, next experiment needs ~%.0f – stopping", elapsed,
                     budget_min, est)
            break
        spec = next(specs)
        eid = reg.new_experiment(spec["family"], spec)
        watcher.cur.update(eid=eid, stage="download", epochs=spec.get("epochs"))
        lab.progress(eid, "download", spec=spec)
        log.info("lab experiment %d: %s %s on %s", len(results) + 1, eid, spec["family"], spec["pairs"])
        started, t1 = iso(), time.time()
        try:
            res = pipe.run(eid, spec)
            results.append({"id": eid, "spec": spec, "result": res, "started": started, "finished": iso()})
            lab.progress(eid, "evaluated", verdict=res["verdict"])
        except Exception as e:  # noqa: BLE001
            log.error("experiment %s failed: %s", eid, e)
            results.append({"id": eid, "spec": spec, "error": f"{e}\n{traceback.format_exc()[-800:]}",
                            "started": started, "finished": iso()})
            lab.progress(eid, "failed", error=str(e)[:500])
        durations.append((time.time() - t1) / 60)
        write_json_atomic(jdir / "results-0.json", {"job": 0, "exchange": uni.get("exchange", s.research.exchange),
                                                    "experiments": results})
        prune_scratch(s.jobs_dir, keep=2)
    watcher.stop()
    if not results:
        lab.run_event("end", experiments=0)
        return None

    from datetime import datetime, timezone
    ledger = json.loads(ledger_path.read_text()) if ledger_path and ledger_path.exists() else {"trials": []}
    batch_id = f"b{datetime.now(timezone.utc):%Y%m%d}-{run_id}"
    m = merge([jdir], batch_id, ledger)
    m["market"], m["universe"] = uni.get("market", {}), pairs
    imp = {k: v for k, v in m.items() if k != "experiments"} | {"summary": m["experiments"]}
    (export / "imports").mkdir(parents=True, exist_ok=True)
    (export / "reports").mkdir(parents=True, exist_ok=True)
    write_json_atomic(export / "imports" / f"{batch_id}.json", imp)
    (export / "reports" / f"{batch_id}.md").write_text(report_md(m))
    write_json_atomic(export / "ledger.json", update_ledger(ledger, m))
    resp = lab.import_batch(imp)
    log.info("batch %s: %d experiments, %d candidates; server import: %s", batch_id, len(results),
             len(m["candidates"]), resp)
    lab.run_event("end", experiments=len(results), candidates=len(m["candidates"]), batch=batch_id)
    return m


def prune_scratch(jobs_dir: Path, keep: int = 2) -> None:
    import shutil
    dirs = sorted((d for d in jobs_dir.iterdir() if d.is_dir() and not d.name.startswith("_")),
                  key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs[keep:]:
        shutil.rmtree(d, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("scan")
    a.add_argument("--out", type=Path, required=True)
    b = sub.add_parser("run")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--job", type=int, default=0)
    b.add_argument("--experiments", type=int, default=4)
    b.add_argument("--universe", type=Path, required=True)
    y = sub.add_parser("cycle", help="research-lab run: state → plan → experiments → merge → import")
    y.add_argument("--out", type=Path, required=True)
    y.add_argument("--export", type=Path, required=True)
    y.add_argument("--budget-min", type=float, default=25)
    y.add_argument("--max-experiments", type=int, default=50)
    y.add_argument("--run-id", default="local")
    y.add_argument("--server", default=None)
    y.add_argument("--ledger", type=Path, default=None)
    c = sub.add_parser("merge")
    c.add_argument("dirs", type=Path, nargs="+")
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--report", type=Path, required=True)
    c.add_argument("--batch-id", required=True)
    args = ap.parse_args()
    if args.cmd == "scan":
        args.out.mkdir(parents=True, exist_ok=True)
        cmd_scan(args.out)
    elif args.cmd == "cycle":
        cmd_cycle(args.out, args.budget_min, args.run_id, args.server, args.max_experiments, args.ledger,
                  args.export)
    elif args.cmd == "run":
        args.out.mkdir(parents=True, exist_ok=True)
        cmd_run(args.out, args.job, args.experiments, args.universe)
    else:
        m = merge(args.dirs, args.batch_id)
        write_json_atomic(args.out, {k: v for k, v in m.items() if k != "experiments"} | {"summary": m["experiments"]})
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report_md(m))
        print(f"{len(m['candidates'])} candidates from {m['n_completed']} experiments")


if __name__ == "__main__":
    main()
