"""Registry, lifecycle, learner, kill-switch and a full research pipeline run with a fake
Freqtrade runner (the real CLI is exercised on the deployed server by the self-test)."""

import json
import zipfile
from pathlib import Path

import pytest
from helpers import make_trades

from aitrader.learner import Learner, mfe_r
from aitrader.lifecycle import Lifecycle
from aitrader.manager import bot_equity, kill_switch
from aitrader.manifest import Manifest
from aitrader.registry import Registry
from aitrader.research.generator import Generator
from aitrader.research.pipeline import Pipeline
from aitrader.settings import Settings
from aitrader.util import iso


@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=tmp_path, app_dir=Path(__file__).resolve().parents[1])
    s.ensure_dirs()
    return s, Registry(s.registry_path)


def _strategy(reg, sid, stage, pairs, score=1.0, family="trend_ema"):
    reg.upsert("strategies", {"id": sid, "experiment_id": "", "family": family, "params": {},
                              "pairs": pairs, "sides": ["long", "short"], "stage": stage,
                              "score": score, "oos": {}, "gates": {}, "live": {}, "created": "2020-01-01",
                              "updated": iso(), "stage_since": "2020-01-01T00:00:00Z", "history": []})


def test_bootstrap_and_manifest(env):
    s, reg = env
    life = Lifecycle(s, reg)
    life.bootstrap()
    life.bootstrap()  # idempotent
    boots = reg.strategies(("exploration",))
    assert len(boots) == 4
    man = life.build_manifest([], set(), False)
    pairs = [p for sl in man.sleeves for p in sl.pairs]
    assert len(pairs) == len(set(pairs)) == 8  # disjoint ownership
    assert all(sl.risk == s.lifecycle.risk_exploration for sl in man.sleeves)
    assert life.write(man, [])
    assert not life.write(life.build_manifest([], set(), False), [])  # unchanged → no rewrite
    pl = json.loads(s.pairlist_path.read_text())
    assert len(pl["pairs"]) == 8


def test_manifest_priority_exclusion_and_closing(env):
    s, reg = env
    life = Lifecycle(s, reg)
    _strategy(reg, "prod", "production", ["BTC", "ETH"], 2.0)
    _strategy(reg, "inc", "incubation", ["ETH", "SOL"], 5.0)
    _strategy(reg, "old", "retired", ["XRP"])
    man = life.build_manifest([{"enter_tag": "old", "pair": "XRP"}], {"SOL"}, False)
    by = {x.id: x for x in man.sleeves}
    assert by["prod"].pairs == ["BTC", "ETH"] and by["prod"].risk == s.lifecycle.risk_production
    assert "inc" not in by  # ETH taken by production, SOL excluded → no pairs left
    assert by["old"].stage == "closing" and by["old"].pairs == []


def _live(reg, sid, pnls):
    learner = Learner(Settings(), reg)
    base = 1000 + len(reg.q("SELECT trade_id FROM live_trades"))
    trades = make_trades(pnls, tag=sid)
    for i, t in enumerate(trades):
        t["trade_id"] = base + i
    learner.sync_trades(trades)


def test_lifecycle_exploration_to_incubation_to_production(env):
    s, reg = env
    life = Lifecycle(s, reg)
    _strategy(reg, "e1", "exploration", ["BTC"])
    _live(reg, "e1", [30, -10] * 10)
    life.evaluate(10_000)
    assert reg.one("SELECT stage FROM strategies WHERE id='e1'")["stage"] == "incubation"
    reg.update("strategies", "e1", {"stage_since": "2020-01-01T00:00:00Z"})
    life.evaluate(10_000)  # incubation passes (old stage_since, ≥15 trades, PF 3) → eligible → production
    assert reg.one("SELECT stage FROM strategies WHERE id='e1'")["stage"] == "production"


def test_lifecycle_retires_losers_and_fills_slots(env):
    s, reg = env
    life = Lifecycle(s, reg)
    _strategy(reg, "bad", "exploration", ["BTC"])
    _live(reg, "bad", [-30, 10] * 10)
    _strategy(reg, "v1", "validated", ["ETH"])
    _strategy(reg, "x1", "exploratory", ["SOL"])
    life.evaluate(10_000)
    st = {r["id"]: r["stage"] for r in reg.strategies()}
    assert st["bad"] == "retired" and st["v1"] == "incubation" and st["x1"] == "exploration"
    hist = reg.one("SELECT history FROM strategies WHERE id='bad'")["history"]
    assert hist[-1]["to"] == "retired"


def test_learner_pair_exclusion_and_exit_analysis(env):
    s, reg = env
    _strategy(reg, "t1", "production", ["BTC/USDT:USDT"])
    pnls = [-20] * 10 + [5] * 6
    _live(reg, "t1", pnls)
    learner = Learner(s, reg)
    learner.analyze_live()
    ls = reg.q("SELECT * FROM learnings")
    assert any(r["scope"] == "pair" and r["adjustment"]["exclude_pair"] == "BTC/USDT:USDT" for r in ls)
    # losing trades had max_rate 103 vs stop 98 → MFE 1.5R → "earlier trailing" learning
    assert any(r["scope"] == "family" and "trail_rr" in r["adjustment"].get("space", {}) for r in ls)
    assert mfe_r({"open_rate": 100, "initial_stop_loss_abs": 98, "max_rate": 103, "is_short": False}) == 1.5


def test_kill_switch(env):
    _, reg = env
    assert not kill_switch(reg, 10_000, 0.25, 48)
    assert not kill_switch(reg, 8_000, 0.25, 48)
    assert kill_switch(reg, 7_400, 0.25, 48)
    assert kill_switch(reg, 9_000, 0.25, 48)  # stays paused during cooldown
    reg.kv_set("kill_since", "2020-01-01T00:00:00Z")
    assert not kill_switch(reg, 9_000, 0.25, 48)


def test_bot_equity():
    eq, free = bot_equity({"total_bot": 5000, "stake": "USDT",
                           "currencies": [{"currency": "USDT", "free": 4000}]})
    assert eq == 5000 and free == 4000


# ------------------------------------------------------------------ pipeline e2e
class FakeRunner:
    """Mimics Freqtrade's CLI outputs (file formats verified against freqtrade 2026.10)."""

    def __init__(self, good: bool):
        self.good = good
        self.calls = []

    def write_config(self, job, name, cfg):
        p = job.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg))
        return p

    def download(self, job, config, pairs, timerange):
        self.calls.append("download")

    def hyperopt(self, job, configs, strategy, timerange, epochs, fee, seed, min_trades, space_file):
        self.calls.append("hyperopt")
        hd = job.userdir / "hyperopt_results"
        hd.mkdir(parents=True, exist_ok=True)
        eps = [{"loss": -1.0 - i * 0.1, "params_dict": {"fast": 10 + i, "sl_atr": 2.0},
                "results_metrics": {"total_trades": 80, "profit_total": 0.3, "sharpe": 1.5 + i * 0.1}}
               for i in range(5)]
        (hd / "s.fthypt").write_text("\n".join(json.dumps(e) for e in eps))
        (hd / ".last_result.json").write_text(json.dumps({"latest_hyperopt": "s.fthypt"}))
        return hd

    def backtest(self, job, configs, strategy, timerange, fee, out_name):
        self.calls.append(f"backtest:{out_name}")
        out = job.path(out_name)
        out.mkdir(parents=True, exist_ok=True)
        start = f"{timerange[:4]}-{timerange[4:6]}-{timerange[6:8]}"
        pattern = [40, -15, 25, -10] if self.good else [-40, 15, -25, 10]
        if "stress" in out_name:
            pattern = [p - 3 for p in pattern]
        trades = make_trades(pattern * 9, start=start, hours=40)
        for i, t in enumerate(trades):
            t["pair"] = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"][i % 3]
        zname = "backtest-result-x.zip"
        with zipfile.ZipFile(out / zname, "w") as zf:
            zf.writestr("backtest-result-x.json", json.dumps({"strategy": {"AIPortfolio": {"trades": trades}}}))
        (out / ".last_result.json").write_text(json.dumps({"latest_backtest": zname}))
        return out


@pytest.mark.parametrize("good", [True, False])
def test_pipeline_end_to_end(env, good):
    s, reg = env
    s.research.perturbations = 3
    runner = FakeRunner(good)
    gen = Generator(s, reg, seed=1)
    spec = gen.next_spec(["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT"])
    spec["family"] = "trend_ema"
    eid = reg.new_experiment(spec["family"], spec)
    res = Pipeline(s, reg, runner).run(eid, spec)
    assert runner.calls.count("hyperopt") == s.research.wf_folds
    assert any(c.startswith("backtest:bt_stress") for c in runner.calls)
    assert any(c.startswith("backtest:bt_pert") for c in runner.calls)
    assert res["oos"]["trades"] == 72
    assert set(res["gates"]) >= {"trades", "profit_factor", "deflated_sharpe", "monte_carlo", "robustness", "wfe"}
    st = reg.one("SELECT * FROM strategies WHERE experiment_id=?", (eid,))
    if good:
        assert res["verdict"] in ("validated", "exploratory") and st["stage"] in ("validated", "exploratory")
        assert set(st["pairs"]) == {"BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"}
        assert st["params"]["fast"] == 14  # best (lowest-loss) epoch of the last fold
    else:
        assert res["verdict"] == "rejected" and st["stage"] == "rejected"
    # validated strategies flow into the manifest
    Lifecycle(s, reg).evaluate(10_000)
    man = Manifest.from_dict(Lifecycle(s, reg).build_manifest([], set(), False).to_dict())
    assert (st["id"] in {x.id for x in man.sleeves}) == good


def test_runner_creates_userdir(env, monkeypatch):
    """freqtrade exits with 'Directory ... does not exist' for a missing --userdir (seen in CI)."""
    import subprocess

    from aitrader.research.ftrunner import FreqtradeRunner, Job
    s, _ = env
    seen = {}

    def fake_run(cmd, **kw):
        seen["userdir_exists"] = Path(cmd[cmd.index("--userdir") + 1]).is_dir()
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    job = Job(s.jobs_dir / "xtest")
    FreqtradeRunner(s).test_pairlist(job, job.path("c.json"))
    assert seen["userdir_exists"]
