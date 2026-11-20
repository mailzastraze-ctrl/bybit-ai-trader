"""Research lab: GitHub OIDC auth, state → cycle → import loop, ledger-wide Deflated Sharpe."""

import json
import time
from datetime import timedelta
from pathlib import Path

import pytest
from test_lifecycle import FakeRunner

from aitrader import lab
from aitrader.families import FAMILIES
from aitrader.lifecycle import Lifecycle
from aitrader.registry import Registry
from aitrader.research import batch
from aitrader.research.generator import Generator
from aitrader.research.pipeline import Pipeline
from aitrader.settings import Settings
from aitrader.util import iso, utcnow

PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT",
         "ADA/USDT:USDT", "LINK/USDT:USDT"]


@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=tmp_path, app_dir=Path(__file__).resolve().parents[1])
    s.ensure_dirs()
    return s, Registry(s.registry_path)


# ------------------------------------------------------------------ OIDC
def _keys():
    pytest.importorskip("jwt")
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric import rsa
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _Jwk:
    def __init__(self, pub):
        self.key = pub

    def get_signing_key_from_jwt(self, token):
        return self


def _token(key, **over):
    import jwt
    now = int(time.time())
    claims = {"iss": lab.OIDC_ISSUER, "aud": lab.AUDIENCE, "iat": now, "exp": now + 300,
              "repository": "mailzastraze-ctrl/bybit-ai-trader", "ref": "refs/heads/main"} | over
    return jwt.encode(claims, key, algorithm="RS256")


def test_oidc_accepts_only_this_repo_main_branch():
    key = _keys()
    jw = _Jwk(key.public_key())
    repo = "mailzastraze-ctrl/bybit-ai-trader"
    assert lab.verify_oidc(_token(key), repo, jw)["repository"] == repo
    for bad in (dict(repository="someone/fork"), dict(ref="refs/heads/feature"), dict(aud="other"),
                dict(iss="https://evil"), dict(exp=int(time.time()) - 10)):
        with pytest.raises(lab.LabAuthError):
            lab.verify_oidc(_token(key, **bad), repo, jw)
    with pytest.raises(lab.LabAuthError):
        lab.verify_oidc(_token(_keys()), repo, jw)  # signed by someone else
    with pytest.raises(lab.LabAuthError):
        lab.verify_oidc("", repo, jw)


# ------------------------------------------------------------------ planner
def test_refine_spec_pins_genes_and_narrows_space(env):
    s, reg = env
    gen = Generator(s, reg, seed=3)
    fam = FAMILIES["trend_ema"]
    params = fam.normalize({"htf_trend": 1, "vol_regime": 2, "sl_atr": 2.0})
    spec = gen.refine_spec(PAIRS, {"id": "c1", "family": "trend_ema", "params": params,
                                   "pairs": ["XRP/USDT:USDT"], "sides": ["long"]})
    ov = spec["space_overrides"]
    assert ov["htf_trend"] == [1, 1] and ov["vol_regime"] == [2, 2]
    lo, hi = ov["sl_atr"]
    assert lo < 2.0 < hi and hi - lo <= (4.0 - 1.0) * 0.4 + 1e-9
    assert fam.space(ov)["htf_trend"] == (1, 1)  # pinned, not reset to the full range
    assert "XRP/USDT:USDT" in spec["pairs"] and spec["refines"] == "c1" and spec["sides"] == ["long"]


def test_family_stats_override(env):
    s, reg = env
    g = Generator(s, reg, stats_override={"trend_ema": [10, 0.5], "bogus": [1, 1]})
    st = g.family_stats()
    assert st["trend_ema"] == (10, 0.5) and set(st) == set(FAMILIES)


def test_ledger_window_counts_all_recent_trials():
    old = iso(utcnow() - timedelta(days=200))
    led = {"trials": [{"ts": iso(), "sr": 0.1}] * 30 + [{"ts": old, "sr": 0.5}] * 10}
    assert len(batch.ledger_trials(led)) == 30


# ------------------------------------------------------------------ full loop
class FakeLab:
    def __init__(self, state):
        self.st, self.events, self.prog, self.imported = state, [], [], None
        self.enabled = True

    def state(self):
        return self.st

    def run_event(self, kind, **kw):
        self.events.append(kind)

    def progress(self, eid, stage, force=True, **kw):
        self.prog.append((eid, stage))

    def import_batch(self, data):
        self.imported = data
        return {"ok": True}


def test_cycle_state_to_import_closed_loop(env, tmp_path, monkeypatch):
    s, server = env
    s.research.perturbations = 2
    # server: a production strategy overdue for revalidation + learnings
    server.upsert("strategies", {"id": "prod-1", "experiment_id": "", "family": "meanrev_bb", "params": {},
                                 "pairs": ["ETH/USDT:USDT"], "sides": ["long", "short"], "stage": "production",
                                 "score": 1.0, "oos": {}, "gates": {}, "live": {}, "created": "2020-01-01",
                                 "updated": iso(), "stage_since": "2020-01-01T00:00:00Z", "history": []})
    state = lab.build_state(s, server)
    assert [r["id"] for r in state["revalidate"]] == ["prod-1"]

    # lab side (separate data dir, like the GitHub runner)
    ls = Settings(data_dir=tmp_path / "runner", app_dir=s.app_dir)
    ls.research.perturbations = 2
    ls.ensure_dirs()
    out = tmp_path / "runner" / "batch"
    out.mkdir(parents=True)
    (out / "universe.json").write_text(json.dumps({"ts": iso(), "exchange": "okx", "pairs": PAIRS, "market": {}}))
    fake = FakeLab(json.loads(json.dumps(state, default=str)))
    monkeypatch.setattr(batch, "get_settings", lambda: ls)
    monkeypatch.setattr(batch, "Pipeline", lambda st, rg, **kw: Pipeline(st, rg, FakeRunner(False), **kw))
    import aitrader.research.labclient as lc
    monkeypatch.setattr(lc, "LabClient", lambda server, run_id: fake)
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"trials": [{"ts": iso(), "sr": 0.01 * i} for i in range(20)]}))
    m = batch.cmd_cycle(out, budget_min=600, run_id="777", server="x", max_exp=3, ledger_path=ledger,
                        export=tmp_path / "export")
    assert m["n_completed"] == 3 and m["n_trials_for_dsr"] == 23  # ledger trials count too
    assert fake.events[0] == "start" and fake.events[-1] == "end"
    assert m["experiments_full"][0]["spec"]["revalidates"] == "prod-1"  # revalidation first
    assert {st for _, st in fake.prog} >= {"download", "hyperopt fold 1/4", "evaluated"}
    assert len(json.loads((tmp_path / "export" / "ledger.json").read_text())["trials"]) == 23
    assert (tmp_path / "export" / "reports" / f"{m['batch_id']}.md").exists()

    # server imports: experiments recorded, failed revalidation retires prod-1, universe set
    res = lab.apply_import(s, server, json.loads(json.dumps(fake.imported, default=str)))
    assert res["experiments"] == 3
    assert server.one("SELECT stage FROM strategies WHERE id='prod-1'")["stage"] == "retired"
    assert server.one("SELECT COUNT(*) n FROM experiments WHERE status='done'")["n"] == 3
    assert (server.kv_get("universe") or {}).get("pairs") == PAIRS
    assert "prod-1" in (server.kv_get("revalidated") or {})
    st2 = lab.build_state(s, server)
    assert st2["revalidate"] == [] and sum(n for n, _ in st2["family_stats"].values()) == 3


def test_progress_and_lost_runs(env):
    s, reg = env
    lab.record_run(reg, {"kind": "start", "run_id": "9", "budget_min": 150, "cpus": 4, "public": True})
    lab.record_progress(reg, {"experiment": "xabc", "stage": "download", "run_id": "9",
                              "spec": {"family": "trend_ema", "pairs": PAIRS[:3]}})
    lab.record_progress(reg, {"experiment": "xabc", "stage": "hyperopt fold 1/2", "epoch": 12, "epochs": 60})
    e = reg.one("SELECT * FROM experiments WHERE id='xabc'")
    assert e["status"] == "running" and e["progress"]["epoch"] == 12 and e["progress"]["remote"]
    assert reg.kv_get("lab")["public"] is True
    reg.update("experiments", "xabc", {"progress": {"remote": True, "ts": iso(utcnow() - timedelta(hours=4))}})
    lab.build_state(s, reg)
    assert reg.one("SELECT status FROM experiments WHERE id='xabc'")["status"] == "failed"


def test_remote_mode_default_in_lite(monkeypatch, tmp_path):
    monkeypatch.setenv("AITRADER_PROFILE", "lite")
    assert Settings(data_dir=tmp_path).research.mode == "remote"
    monkeypatch.setenv("RESEARCH_MODE", "local")
    assert Settings(data_dir=tmp_path).research.mode == "local"


def test_imported_candidate_flows_to_exploration(env):
    s, reg = env
    data = {"batch_id": "b1-1", "exchange": "okx", "n_trials_for_dsr": 40, "experiments_full": [],
            "candidates": [{"id": "b1-1-trend-00", "family": "trend_ema", "params": {}, "pairs": ["BTC/USDT:USDT"],
                            "stage": "exploratory", "score": 0.4, "oos": {"profit_factor": 1.3, "sharpe": 1.1}}]}
    lab.apply_import(s, reg, data)
    Lifecycle(s, reg).evaluate(10_000)
    assert reg.one("SELECT stage FROM strategies WHERE id='b1-1-trend-00'")["stage"] == "exploration"


def test_fold_consistency_gate():
    from aitrader.research.validation import evaluate_gates
    from aitrader.settings import Gates
    oos = {"trades": 80, "profit_factor": 1.5, "sharpe": 1.4, "max_drawdown": 0.05, "total_return": 0.2}
    m = {"oos": oos, "stress": {"profit_factor": 1.3}, "wfe": 0.8, "robust_frac": 1.0, "mc": {"prob_profit": 0.95},
         "dsr": 0.95}
    assert evaluate_gates(Gates(), m)[0] == "validated"  # old results without fold data
    v, g = evaluate_gates(Gates(), {**m, "fold_pos": 0.5})  # only 2 of 4 slices profitable
    assert v == "exploratory" and g["fold_consistency"]["pass"] is False
    assert evaluate_gates(Gates(), {**m, "fold_pos": 0.25})[0] == "rejected"
