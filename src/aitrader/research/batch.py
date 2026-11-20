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


def cmd_scan(out: Path) -> None:
    from aitrader.scanner import Scanner
    s = get_settings()
    s.ensure_dirs()
    reg = Registry(out / "scan.sqlite")
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
        try:
            res = pipe.run(eid, spec)
            results.append({"id": eid, "spec": spec, "result": res})
        except Exception as e:  # noqa: BLE001
            log.error("experiment %s failed: %s", eid, e)
            results.append({"id": eid, "spec": spec, "error": f"{e}\n{traceback.format_exc()[-800:]}"})
        write_json_atomic(out / f"results-{job}.json", {"job": job, "exchange": uni.get("exchange", s.research.exchange),
                                                        "experiments": results})


def merge(dirs: list[Path], batch_id: str) -> dict:
    s = get_settings()
    exps, exchange = [], None
    for d in dirs:
        for f in sorted(Path(d).rglob("results-*.json")):
            data = json.loads(f.read_text())
            exchange = data.get("exchange", exchange)
            exps += data["experiments"]
    done = [e for e in exps if "result" in e]
    srs = [e["result"]["oos"].get("daily_sharpe", 0.0) for e in done]
    n_trials = max(len(done), 1)
    var = statistics.pvariance(srs) if len(srs) >= 5 else 1.0 / 365.0
    candidates = []
    for idx, e in enumerate(done):
        r = e["result"]
        oos = r["oos"]
        dsr = M.deflated_sharpe(oos.get("daily_sharpe", 0.0), oos.get("n_days", 0), n_trials, max(var, 1e-6),
                                oos.get("skew", 0.0), oos.get("kurtosis", 3.0))
        verdict, gates = evaluate_gates(s.gates, {"oos": oos, "stress": r["stress"], "wfe": r["wfe"],
                                                  "robust_frac": r["robust_frac"], "mc": r["mc"], "dsr": dsr})
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
    return {"batch_id": batch_id, "created": iso(), "exchange": exchange, "n_experiments": len(exps),
            "n_completed": len(done), "n_trials_for_dsr": n_trials, "candidates": candidates,
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
    c = sub.add_parser("merge")
    c.add_argument("dirs", type=Path, nargs="+")
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--report", type=Path, required=True)
    c.add_argument("--batch-id", required=True)
    args = ap.parse_args()
    if args.cmd == "scan":
        args.out.mkdir(parents=True, exist_ok=True)
        cmd_scan(args.out)
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
