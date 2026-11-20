"""Research-lab sync (server side).

Heavy research (hyperopt, walk-forward backtests) runs on GitHub Actions runners. The
live server stays light: it tells the lab what to work on (`build_state`), shows the
lab's live progress (`record_progress`) and imports the finished, gate-checked results
(`apply_import`). The learner then turns those results into new search directions,
which the next lab run picks up — a closed loop without heavy compute on the server.

Authentication: GitHub Actions OIDC tokens (no shared secret). A token is accepted only
if GitHub signed it, it was minted for our audience, and it belongs to the configured
repository's main branch.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

from aitrader import forward
from aitrader.learner import Learner
from aitrader.lifecycle import DEPLOYED, Lifecycle
from aitrader.registry import Registry
from aitrader.research.generator import Generator
from aitrader.settings import Settings
from aitrader.util import iso, parse_dt, utcnow

log = logging.getLogger(__name__)

OIDC_ISSUER = "https://token.actions.githubusercontent.com"
OIDC_JWKS = OIDC_ISSUER + "/.well-known/jwks"
AUDIENCE = "aitrader-lab"
REVALIDATE_DAYS = 14
STALE_RUNNING_H = 3
_jwk_client = None
_jwk_lock = threading.Lock()


class LabAuthError(Exception):
    pass


def verify_oidc(token: str, repository: str, jwk_client=None) -> dict:
    """Validate a GitHub Actions OIDC token; returns its claims."""
    import jwt  # PyJWT (ships with freqtrade)

    global _jwk_client
    if not token:
        raise LabAuthError("missing token")
    if jwk_client is None:
        with _jwk_lock:
            if _jwk_client is None:
                _jwk_client = jwt.PyJWKClient(OIDC_JWKS, cache_keys=True, lifespan=3600)
            jwk_client = _jwk_client
    try:
        key = jwk_client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=AUDIENCE, issuer=OIDC_ISSUER,
                            options={"require": ["exp", "iat", "iss", "aud"]})
    except Exception as e:  # noqa: BLE001
        raise LabAuthError(f"invalid token: {e}") from e
    if str(claims.get("repository", "")).lower() != repository.lower():
        raise LabAuthError(f"token belongs to {claims.get('repository')}")
    if claims.get("ref") != "refs/heads/main":
        raise LabAuthError(f"token minted for {claims.get('ref')}, not main")
    return claims


# ---------------------------------------------------------------------------- state
def _expire_lost_runs(reg: Registry) -> None:
    """Remote experiments whose progress stopped (runner cancelled/crashed) → failed."""
    cutoff = utcnow() - timedelta(hours=STALE_RUNNING_H)
    for r in reg.q("SELECT id, progress, started FROM experiments WHERE status='running'"):
        p = r.get("progress") if isinstance(r.get("progress"), dict) else {}
        if not p.get("remote"):
            continue
        ts = parse_dt(p.get("ts") or r.get("started"))
        if ts is None or ts < cutoff:
            reg.update("experiments", r["id"], {"status": "failed", "finished": iso(),
                                                "error": "research-lab run lost (no progress for 3h)"})


def revalidation_due(reg: Registry, now=None) -> list[dict]:
    now = now or utcnow()
    marks = reg.kv_get("revalidated") or {}
    out = []
    for st in reg.q("SELECT id, family, params, pairs, sides, stage, stage_since, oos FROM strategies "
                    "WHERE stage IN ('production','incubation','eligible') ORDER BY score DESC"):
        ref = parse_dt(marks.get(st["id"])) or parse_dt(st.get("stage_since"))
        if ref is not None and (now - ref).days >= REVALIDATE_DAYS:
            out.append({k: st[k] for k in ("id", "family", "params", "pairs", "sides", "stage")}
                       | {"timeframe": (st.get("oos") or {}).get("timeframe") or "1h"})
    return out


def refine_pool(reg: Registry, k: int = 5) -> list[dict]:
    """Research-backed strategies worth refining: positive live forward evidence first,
    then the best out-of-sample candidates. Random/boot placeholders are excluded."""
    rows = reg.q("SELECT id, family, params, pairs, sides, stage, score, oos, live FROM strategies "
                 "WHERE stage IN ('exploratory','exploration','incubation','eligible','production')")
    out = []
    for r in rows:
        if str(r["id"]).startswith(("boot-", "rnd-")) or not r.get("pairs"):
            continue
        live = r.get("live") or {}
        if live.get("trades", 0) >= 5 and live.get("pnl", 0) < 0:
            continue  # live evidence says no – don't spend compute polishing it
        prio = (1 if live.get("trades", 0) >= 5 else 0, float(r.get("score") or 0))
        out.append((prio, {k: r.get(k) for k in ("id", "family", "params", "pairs", "sides", "stage", "score")}
                    | {"live": live, "timeframe": (r.get("oos") or {}).get("timeframe") or "1h"}))
    out.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in out[:k]]


def purge_broken_runs(reg: Registry) -> int:
    """Experiments that never had pairs (a broken lab run) are not research – remove them."""
    rows = reg.q("SELECT id, spec FROM experiments WHERE status='failed'")
    bad = [r["id"] for r in rows if isinstance(r.get("spec"), dict) and not r["spec"].get("pairs")]
    with reg.conn() as c:
        for eid in bad:
            c.execute("DELETE FROM experiments WHERE id=?", (eid,))
    return len(bad)


def build_state(s: Settings, reg: Registry) -> dict:
    _expire_lost_runs(reg)
    if purge_broken_runs(reg):
        reg.event("research", "lab: removed experiments of a broken run (no pairs) from the research record")
    now = iso()
    learnings = [lr for lr in reg.q("SELECT id, scope, key, insight, adjustment, expires FROM learnings WHERE active=1")
                 if not lr.get("expires") or lr["expires"] > now]
    srs = [r["result"]["oos"]["daily_sharpe"] for r in
           reg.q("SELECT result FROM experiments WHERE status='done' AND finished >= ?",
                 (iso(utcnow() - timedelta(days=90)),))
           if isinstance(r.get("result"), dict) and isinstance(r["result"].get("oos"), dict)
           and "daily_sharpe" in r["result"]["oos"]]
    return {
        "ts": now,
        "paused": bool(reg.kv_get("research_paused", False)),
        "family_stats": Generator(s, reg).family_stats(),
        "learnings": learnings,
        "revalidate": revalidation_due(reg),
        "refine": refine_pool(reg),
        "deployed": [{"id": r["id"], "family": r["family"], "stage": r["stage"], "pairs": r.get("pairs"),
                      "live": r.get("live")} for r in reg.strategies(DEPLOYED)],
        "server_trials_90d": len(srs),
        "universe": reg.kv_get("universe"),
        "shadow": forward.book(reg),
        "external_tests": external_tests(reg),
    }


def external_tests(reg: Registry) -> list[dict]:
    """External strategies (e.g. the owner's Strategy Lab) not yet walk-forward tested."""
    done = reg.kv_get("external_tested") or {}
    out = []
    for st in reg.q("SELECT id, family, params, pairs, sides, oos FROM strategies WHERE stage != 'retired'"):
        oos = st.get("oos") or {}
        if oos.get("external") and st["id"] not in done:
            out.append({"id": st["id"], "family": st["family"], "params": st["params"], "pairs": st["pairs"],
                        "sides": st.get("sides"), "timeframe": oos.get("timeframe") or "1h"})
    return out


# ---------------------------------------------------------------------------- progress
def record_progress(reg: Registry, p: dict) -> None:
    """Live progress of a remote experiment (started / stage / epochs / finished)."""
    eid = str(p.get("experiment") or "")
    if not eid.startswith("x"):
        return
    run = {"remote": True, "run_id": p.get("run_id"), "ts": iso()}
    prog = {k: p[k] for k in ("stage", "epoch", "epochs", "best_loss", "best_trades", "best_profit",
                              "fold", "job", "budget_left_min") if k in p} | run
    row = reg.one("SELECT id, status FROM experiments WHERE id=?", (eid,))
    if row is None:
        spec = p.get("spec") or {}
        reg.upsert("experiments", {"id": eid, "created": iso(), "family": spec.get("family", "?"),
                                   "spec": spec | {"remote": p.get("run_id")}, "status": "running",
                                   "started": iso(), "progress": prog})
        what = ("revalidates " + spec["revalidates"]) if spec.get("revalidates") else \
            ("refines " + spec["refines"]) if spec.get("refines") else "new search"
        reg.event("research", f"lab: experiment {eid} started — {spec.get('family')} on "
                  f"{len(spec.get('pairs') or [])} pairs ({what})",
                  data={"experiment": eid, "family": spec.get("family"), "lab": True})
    elif row["status"] == "running":
        reg.update("experiments", eid, {"progress": prog})
    if p.get("stage") == "failed":
        reg.update("experiments", eid, {"status": "failed", "finished": iso(),
                                        "error": str(p.get("error") or "")[:2000]})
        reg.event("research", f"lab: experiment {eid} failed: {str(p.get('error'))[:200]}", "warning",
                  data={"experiment": eid})
    reg.heartbeat("research", "busy" if p.get("stage") not in ("idle", "failed") else "idle",
                  {"remote": True, "experiment": eid, "stage": p.get("stage"), "run_id": p.get("run_id")})


def record_run(reg: Registry, p: dict) -> None:
    """Run-level lab notices (started / finished / scan)."""
    kind = p.get("kind")
    lab = reg.kv_get("lab") or {}
    lab.update({"ts": iso(), "run_id": p.get("run_id"), "status": kind,
                "budget_min": p.get("budget_min", lab.get("budget_min")),
                "cpus": p.get("cpus", lab.get("cpus")), "public": p.get("public", lab.get("public"))})
    if kind == "start":
        lab["runs"] = int(lab.get("runs", 0)) + 1
        lab["started"] = iso()
        reg.event("research", f"lab: GitHub research run {p.get('run_id')} started "
                  f"({p.get('cpus')} CPUs, budget {p.get('budget_min')} min)", data={"lab": True})
    elif kind == "scan":
        reg.event("scanner", f"lab: universe refreshed on {p.get('exchange')} — {len(p.get('pairs') or [])} pairs",
                  data={"pairs": p.get("pairs")})
    elif kind == "shadow":
        reg.event("research", f"lab: forward test of {p.get('strategies')} frozen strategies on unseen Bybit data "
                  f"— {p.get('trades')} forward trades", data={"lab": True})
        return
    elif kind == "end":
        reg.heartbeat("research", "idle", {"remote": True, "run_id": p.get("run_id")})
    reg.kv_set("lab", lab)


# ---------------------------------------------------------------------------- import
def apply_import(s: Settings, reg: Registry, data: dict) -> dict:
    """Store finished experiments, candidates, market scores; learn; act on revalidations."""
    now = iso()
    fw = forward.apply(reg, data["shadow"]) if data.get("shadow") else None
    if data.get("screen"):
        sc = data["screen"]
        reg.kv_set("screen", sc | {"ts": now})
        reg.event("research", f"screener: {sc.get('evaluated', 0):,} strategy combinations tested on "
                  f"{sc.get('series', 0)} coin/timeframe series — {sc.get('n_survivors', 0)} stayed profitable with a "
                  "steady curve on the unseen last 40% → walk-forward", data={"lab": True})
    if not data.get("experiments_full") and not data.get("candidates"):
        return {"experiments": 0, "candidates": 0, "forward": fw}
    n_exp = 0
    for e in data.get("experiments_full", []):
        eid, spec, res = e.get("id"), e.get("spec") or {}, e.get("result")
        if not eid:
            continue
        if res is None:
            reg.upsert("experiments", {"id": eid, "created": now, "family": spec.get("family", "?"),
                                       "spec": spec, "status": "failed", "finished": now,
                                       "error": str(e.get("error") or "")[:3000], "progress": {"stage": "failed", "remote": True}})
            continue
        reg.upsert("experiments", {"id": eid, "created": e.get("created") or now, "family": spec.get("family", "?"),
                                   "spec": spec, "status": "done", "started": e.get("started"),
                                   "finished": e.get("finished") or now, "result": res,
                                   "progress": {"stage": "done", "remote": True}})
        n_exp += 1
        if spec.get("screen"):
            o = res.get("oos") or {}
            reg.event("research", f"screener survivor {spec['screen']} ({spec.get('family')} {spec.get('timeframe')} "
                      f"{', '.join(spec.get('pairs') or [])}): walk-forward PF {o.get('profit_factor')}, "
                      f"{o.get('trades')} trades, curve R² {o.get('curve_r2')} → {res.get('verdict')}")
        if spec.get("external"):
            marks = reg.kv_get("external_tested") or {}
            marks.setdefault(spec["external"], []).append(eid)
            reg.kv_set("external_tested", marks)
            o = res.get("oos") or {}
            reg.event("research", f"{spec['external']}: walk-forward with its fixed configuration on "
                      f"{len(spec.get('pairs') or [])} pair(s) — unseen-window PF {o.get('profit_factor')}, "
                      f"{o.get('trades')} trades, verdict {res.get('verdict')}", data={"strategy": spec["external"]})
        target = spec.get("revalidates")
        if target:
            marks = reg.kv_get("revalidated") or {}
            marks[target] = now
            reg.kv_set("revalidated", marks)
            pf = float((res.get("oos") or {}).get("profit_factor") or 0)
            st = reg.one("SELECT stage FROM strategies WHERE id=?", (target,))
            if st and st["stage"] in ("incubation", "eligible", "production") \
                    and res.get("verdict") == "rejected" and pf < 1.0:
                reg.set_stage(target, "retired", f"revalidation on fresh data: edge gone (OOS PF {pf})")
            else:
                reg.event("research", f"{target}: revalidation {res.get('verdict')} (OOS PF {pf})")
    market = data.get("market") or {}
    for pair, sc in market.items():
        reg.upsert("market", {"pair": pair, "ts": now, "data": sc}, key="pair")
    if data.get("universe"):
        reg.kv_set("universe", {"ts": now, "pairs": data["universe"], "source": f"lab:{data.get('exchange')}"})
    life = Lifecycle(s, reg)
    n_cand = life.import_batch(data)
    Learner(s, reg).learn_from_research()
    lab = reg.kv_get("lab") or {}
    lab.update({"last_import": now, "last_batch": data.get("batch_id"),
                "experiments_total": int(lab.get("experiments_total", 0)) + n_exp})
    reg.kv_set("lab", lab)
    reg.event("research", f"lab: batch {data.get('batch_id')} imported — {n_exp} experiments, "
              f"{n_cand} new candidates (DSR over N={data.get('n_trials_for_dsr')} trials)", data={"lab": True})
    return {"experiments": n_exp, "candidates": n_cand, "forward": fw}
