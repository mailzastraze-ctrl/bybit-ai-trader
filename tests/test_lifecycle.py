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
    assert by["inc"].pairs == ["ETH"]  # ETH shared with production (independent strategy), SOL excluded
    for i in range(3):  # at most 3 sleeves per pair
        _strategy(reg, f"x{i}", "exploration", ["ETH"], 1.0)
    man = life.build_manifest([], set(), False)
    assert sum(1 for x in man.sleeves if "ETH" in x.pairs) == s.lifecycle.max_sleeves_per_pair
    assert by["old"].stage == "closing" and by["old"].pairs == []


def _live(reg, sid, pnls):
    learner = Learner(Settings(), reg)
    base = 1000 + len(reg.q("SELECT trade_id FROM live_trades"))
    trades = make_trades(pnls, tag=sid)
    for i, t in enumerate(trades):
        t["trade_id"] = base + i
    learner.sync_trades(trades)


def _btc_flat_noise(reg, start="2025-05-01", days=1000, seed=11):
    """BTC daily closes (independent noise): a sleeve's alpha is then simply its own edge."""
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=days, freq="1D", tz="UTC")
    px = 60_000 * np.exp(np.cumsum(rng.normal(0, 0.02, days)))
    reg.kv_set("btc_daily", {d.strftime("%Y-%m-%d"): float(p) for d, p in zip(idx, px, strict=True)})


def test_lifecycle_exploration_to_incubation_to_production(env):
    s, reg = env
    _btc_flat_noise(reg)  # production needs alpha over BTC, measured on BTC daily candles
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
    pnls = [-20] * 20 + [5] * 12  # family patterns need ≥ 30 trades (≥ 12 losers with an MFE)
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

    def download(self, job, config, pairs, timerange, timeframe=None):
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
    assert res["oos"]["trades"] == 36 * s.research.wf_folds
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

    from aitrader.research.ftrunner import FreqtradeRunner, Job
    s, _ = env
    seen = {}

    def fake_run(cmd, **kw):
        seen["userdir_exists"] = Path(cmd[cmd.index("--userdir") + 1]).is_dir()
        return 0, "[]"

    from aitrader.research import ftrunner
    monkeypatch.setattr(ftrunner, "run_supervised", fake_run)
    job = Job(s.jobs_dir / "xtest")
    FreqtradeRunner(s).test_pairlist(job, job.path("c.json"))
    assert seen["userdir_exists"]


def test_prune_jobs_and_lite_profile(tmp_path, monkeypatch):
    import os
    import time

    from aitrader.research.worker import KEEP_JOBS, prune_jobs
    for i in range(KEEP_JOBS + 5):
        d = tmp_path / f"x{i:03d}"
        d.mkdir()
        os.utime(d, (time.time() + i, time.time() + i))
    (tmp_path / "_scan").mkdir()
    prune_jobs(tmp_path)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert "_scan" in left and len(left) == KEEP_JOBS + 1 and "x000" not in left
    monkeypatch.setenv("AITRADER_PROFILE", "lite")
    s = Settings()
    assert s.research.hyperopt_jobs == 1 and s.research.epochs == 60


def test_trade_config_pairlist_url_is_absolute():
    """RemotePairList does url.split('file:///')[1] → needs 4 slashes for an absolute path
    (found on first Railway deploy: 'file:///data/...' resolved to relative 'data/...')."""
    cfg = json.loads((Path(__file__).resolve().parents[1] / "config" / "trade.json").read_text())
    url = cfg["pairlists"][0]["pairlist_url"]
    path = url.split("file:///", 1)[1]
    assert path == Settings(data_dir=Path("/data")).pairlist_path.as_posix()
    assert cfg["exchange"]["demo_trading"] is True and cfg["dry_run"] is False


def test_ccxt_loads_linear_markets_only():
    from aitrader.research.ftrunner import research_config, scan_config
    cfg = json.loads((Path(__file__).resolve().parents[1] / "config" / "trade.json").read_text())
    for c in (cfg, research_config(Settings(), ["BTC/USDT:USDT"]), scan_config(Settings())):
        assert c["exchange"]["ccxt_config"]["options"]["fetchMarkets"]["types"] == ["linear"]


def test_batch_run_merge_and_import(env, tmp_path, monkeypatch):
    from aitrader.research import batch
    s, reg = env
    s.research.perturbations = 2
    monkeypatch.setattr(batch, "get_settings", lambda: s)
    monkeypatch.setattr(batch, "Pipeline", lambda st, rg: Pipeline(st, rg, FakeRunner(True)))
    uni = tmp_path / "universe.json"
    uni.write_text(json.dumps({"ts": iso(), "exchange": "okx",
                               "pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT"],
                               "market": {}}))
    for job in (0, 1):
        batch.cmd_run(tmp_path / f"job{job}", job, 2, uni)
    m = batch.merge([tmp_path], "b1")
    assert m["n_completed"] == 4 and m["n_trials_for_dsr"] == 4
    fams = {e["family"] for e in m["experiments"]}
    assert len(fams) == 4 and fams <= set(batch.FAMILIES)
    assert m["candidates"] and all(c["stage"] in ("validated", "exploratory") for c in m["candidates"])
    md = batch.report_md(m)
    assert "Research batch b1" in md and "| Experiment |" in md
    imp = tmp_path / "imports"
    imp.mkdir()
    (imp / "b1.json").write_text(json.dumps({k: v for k, v in m.items() if k != "experiments"}))
    life = Lifecycle(s, reg)
    assert life.import_offline_candidates(imp) == len(m["candidates"])
    assert life.import_offline_candidates(imp) == 0  # idempotent
    # a re-filtered file retracts dropped candidates that were not deployed yet
    dropped = m["candidates"][-1]["id"]
    refiltered = {k: v for k, v in m.items() if k != "experiments"}
    refiltered["candidates"] = m["candidates"][:-1]
    (imp / "b1.json").write_text(json.dumps(refiltered))
    life.import_offline_candidates(imp)
    if reg.one("SELECT stage FROM strategies WHERE id=?", (dropped,))["stage"] != "exploration":
        assert reg.one("SELECT stage FROM strategies WHERE id=?", (dropped,))["stage"] == "rejected"
    st = reg.one("SELECT * FROM strategies WHERE id=?", (m["candidates"][0]["id"],))
    assert "okx data" in st["note"]


def test_always_on_exploration_near_miss_and_random_explorer(env):
    s, reg = env
    life = Lifecycle(s, reg)
    # nothing deployed → random explorers keep live learning going
    life.evaluate(10_000)
    rnd = [r for r in reg.strategies(("exploration",)) if r["id"].startswith("rnd-")]
    assert len(rnd) == 2 and all(r["pairs"] for r in rnd)
    # a profitable near-miss gets an exploration slot
    _strategy(reg, "near", "rejected", ["SOL/USDT:USDT"])
    reg.update("strategies", "near", {"created": iso(), "oos": {"trades": 20, "total_return": 0.03,
                                                                 "profit_factor": 1.1, "sharpe": 0.5}})
    life.evaluate(10_000)
    assert reg.one("SELECT stage FROM strategies WHERE id='near'")["stage"] == "exploration"


def test_volatility_targeting_scales_risk_down(env):
    s, reg = env
    from datetime import timedelta

    import numpy as np

    from aitrader.util import utcnow
    eq = 10_000.0
    rng = np.random.default_rng(0)
    for d in range(10):
        eq *= 1 + rng.choice([-0.06, 0.06])
        for k in range(144):
            ts = (utcnow() - timedelta(days=10 - d, minutes=-10 * k)).strftime("%Y-%m-%dT%H:%M")[:15] + "0"
            reg.upsert("equity", {"ts": ts, "equity": eq, "free": eq, "open_trades": 0}, key="ts")
    sc = Lifecycle(s, reg).portfolio_scale()
    assert 0.5 <= sc < 1.0 and reg.kv_get("risk_scale")["daily_vol"] > 0.015


def test_divergence_retires_and_risk_follows_live_edge(env):
    s, reg = env
    life = Lifecycle(s, reg)
    _strategy(reg, "p1", "production", ["BTC/USDT:USDT"])
    reg.update("strategies", "p1", {"oos": {"expectancy": 0.01}})
    _live(reg, "p1", [-10, -12, 3] * 8)
    life.evaluate(10_000)
    assert reg.one("SELECT stage FROM strategies WHERE id='p1'")["stage"] == "retired"
    assert life.risk_multiplier({"live": {"trades": 40, "profit_factor": 2.0}}) > 1.2
    assert life.risk_multiplier({"live": {"trades": 40, "profit_factor": 0.6}}) < 0.9
    assert life.risk_multiplier({"live": {"trades": 3, "profit_factor": 5}}) == 1.0


def test_revalidation_spec_targets_stale_live_strategy(env):
    s, reg = env
    _strategy(reg, "old", "production", ["BTC/USDT:USDT"], family="meanrev_bb")
    gen = Generator(s, reg, seed=3)
    spec = gen.revalidation_spec(["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT"])
    assert spec["revalidates"] == "old" and spec["family"] == "meanrev_bb" and spec["pairs"][0] == "BTC/USDT:USDT"
    assert gen.revalidation_spec(["BTC/USDT:USDT"]) is None  # marked, not again for 14 days


def test_research_candidates_displace_bootstrap_placeholders(env):
    s, reg = env
    s.lifecycle.max_exploration = 5  # a full lane forces displacement
    s.lifecycle.max_family_sleeves = 2
    life = Lifecycle(s, reg)
    life.bootstrap()  # 4 unvalidated exploration sleeves (more than max_exploration)
    _strategy(reg, "cand1", "exploratory", ["SOL/USDT:USDT"], score=0.8)
    _strategy(reg, "cand2", "exploratory", ["AVAX/USDT:USDT"], score=0.5)
    life.evaluate(10_000)
    st = {r["id"]: r["stage"] for r in reg.strategies()}
    assert st["cand1"] == "exploration" and st["cand2"] == "exploration"
    assert sum(1 for k, v in st.items() if k.startswith("boot-") and v == "retired") >= 1
    # diversification: a third research candidate of the same family waits
    _strategy(reg, "cand3", "exploratory", ["DOT/USDT:USDT"], score=0.9)
    life.evaluate(10_000)
    assert reg.one("SELECT stage FROM strategies WHERE id='cand3'")["stage"] == "exploratory"


def test_autopilot_strategies_take_the_demo_lane_first(env):
    """Strategies found by the Strategy Lab autopilot replace ordinary exploration sleeves
    (near-misses) that have not earned their place live; a proven sleeve keeps its slot."""
    s, reg = env
    s.lifecycle.max_exploration = 2
    life = Lifecycle(s, reg)
    _strategy(reg, "near", "exploration", ["SOL/USDT:USDT"], score=0.3, family="macd_cross")
    reg.update("strategies", "near", {"history": [{"ts": iso(), "to": "exploration",
                                                   "reason": "always-on exploration: near-miss (positive OOS, failed a strict gate)"}]})
    _strategy(reg, "proven", "exploration", ["XRP/USDT:USDT"], score=0.2, family="adx_di")
    reg.update("strategies", "proven", {"live": {"trades": 14, "profit_factor": 1.4}})
    _strategy(reg, "plain", "exploratory", ["DOT/USDT:USDT"], score=0.9, family="supertrend")
    _strategy(reg, "auto", "exploratory", [f"C{i}/USDT:USDT" for i in range(15)], score=0.4, family="ema_cross")
    reg.update("strategies", "auto", {"oos": {"autopilot": True, "timeframe": "6h"}})
    life._fill_slots()
    st = {r["id"]: r["stage"] for r in reg.strategies()}
    assert st["auto"] == "exploration" and st["near"] == "retired" and st["proven"] == "exploration"
    assert st["plain"] == "exploratory"  # an ordinary candidate does not push out others
    assert Lifecycle.tradable_tf({"oos": {"timeframe": "12h"}}) and not Lifecycle.tradable_tf({"oos": {"timeframe": "1d"}})


def test_best_first_a_clearly_better_candidate_takes_a_weak_slot(env):
    """Best first: within the same evidence class a candidate with a clearly higher research score
    (≥ 1.5× and ≥ +0.2) takes the slot of the weakest sleeve that has not earned it live; small
    differences never flip a slot, and a sleeve with a live edge is never moved."""
    s, reg = env
    s.lifecycle.max_exploration = 2
    life = Lifecycle(s, reg)
    _strategy(reg, "weak", "exploration", ["SOL/USDT:USDT"], score=0.3, family="macd_cross")
    _strategy(reg, "ok", "exploration", ["XRP/USDT:USDT"], score=0.8, family="adx_di")
    reg.update("strategies", "weak", {"live": {"trades": 4, "profit_factor": 2.0}, "stage_since": iso()})
    reg.update("strategies", "ok", {"live": {"trades": 3, "profit_factor": 0.9}, "stage_since": iso()})
    _strategy(reg, "close", "exploratory", ["DOT/USDT:USDT"], score=0.4, family="supertrend")   # not clearly better
    _strategy(reg, "best", "exploratory", ["ADA/USDT:USDT"], score=1.6, family="ema_cross")
    life._fill_slots()
    st = {r["id"]: r["stage"] for r in reg.strategies()}
    assert st["best"] == "exploration" and st["weak"] == "exploratory"  # back in the queue, it did not fail
    assert st["ok"] == "exploration" and st["close"] == "exploratory"
    life._fill_slots()  # stable: nothing flips back
    assert {r["id"]: r["stage"] for r in reg.strategies()} == st
    # a sleeve that earned its place live keeps it against any candidate; the weaker one gives way
    reg.update("strategies", "ok", {"live": {"trades": 12, "profit_factor": 1.3}})
    _strategy(reg, "star", "exploratory", ["BNB/USDT:USDT"], score=3.0, family="rsi_revert")
    life._fill_slots()
    st = {r["id"]: r["stage"] for r in reg.strategies()}
    assert st["ok"] == "exploration" and st["star"] == "exploration" and st["best"] == "exploratory"
    assert Lifecycle.outclasses((1, 0.9), (1, 0.3)) and not Lifecycle.outclasses((1, 0.35), (1, 0.3))
    assert Lifecycle.outclasses((2, 0.1), (1, 2.0))


def test_owner_configs_queue_like_autopilot_and_corrected_imports_supersede(env, tmp_path):
    import json
    s, reg = env
    life = Lifecycle(s, reg)
    d = tmp_path / "ext"
    d.mkdir()
    (d / "a.json").write_text(json.dumps({"id": "owner-a", "family": "ema_cross", "timeframe": "6h", "pairs": ["BTC/USDT:USDT"],
                                          "params": {"ema_fast": 47, "ema_slow": 76, "exit_mode": 1}}))
    assert life.import_external(d) == 1
    (d / "b.json").write_text(json.dumps({"id": "owner-a2", "owner": True, "supersedes": "owner-a", "family": "ema_cross",
                                          "timeframe": "6h", "pairs": ["BTC/USDT:USDT"], "params": {"ema_fast": 47, "ema_slow": 76}}))
    assert life.import_external(d) == 1
    st = {r["id"]: r for r in reg.strategies()}
    assert st["owner-a"]["stage"] == "retired" and st["owner-a2"]["stage"] == "exploratory"
    assert life.evidence_rank(st["owner-a2"])[0] == 2  # queued like an autopilot find
    assert life.import_external(d) == 0  # idempotent


def test_crowded_coin_goes_to_the_strongest_evidence_first(env):
    s, reg = env
    s.lifecycle.max_sleeves_per_pair = 1
    life = Lifecycle(s, reg)
    _strategy(reg, "plain", "exploration", ["BTC/USDT:USDT"], score=1.2, family="macd_cross")
    _strategy(reg, "owner-x", "exploration", ["BTC/USDT:USDT"], score=0.0, family="ema_cross")
    reg.update("strategies", "owner-x", {"oos": {"owner": True, "external": True, "timeframe": "6h"}})
    man = life.build_manifest([], set(), False)
    assert [sl.id for sl in man.sleeves] == ["owner-x"]  # the owner's system is not crowded out by score


def test_demo_core_always_trades_its_coins(env):
    """Owner's decision 2026-11-22: the pre-registered TSMOM set (benchmark 30 d + H1 12/84 d,
    4h, 15 coins) always trades on demo at exploration risk – no rotation, first on shared coins."""
    s, reg = env
    life = Lifecycle(s, reg)
    root = Path(__file__).resolve().parents[1] / "research"
    assert life.import_core(root / "external", root / "hypotheses") == 3
    _strategy(reg, "weak", "exploration", ["BTC/USDT:USDT", "PEPE/USDT:USDT"], score=0.4)
    man = life.build_manifest([], {"TRX/USDT:USDT"}, False)
    core = [x for x in man.sleeves if x.id.startswith("core-")]
    assert sorted(x.id for x in core) == ["core-tsmom-4h-12d", "core-tsmom-4h-30d", "core-tsmom-4h-84d"]
    for x in core:
        assert x.stage == "exploration" and x.timeframe == "4h" and x.risk == s.lifecycle.risk_exploration
        assert len(x.pairs) == 14 and "TRX/USDT:USDT" not in x.pairs  # excluded (e.g. delisting) coins still respected
    assert {x.id for x in man.sleeves} >= {"weak"}  # other strategies keep trading
    first = man.sleeves_for("BTC/USDT:USDT")[0]
    assert first.id.startswith("core-")  # the core goes first on a shared coin
    assert set(core[0].pairs) <= set(man.all_pairs())
    # no strategy rows: never rotated, never retired, never a research candidate
    assert not reg.q("SELECT id FROM strategies WHERE id LIKE 'core-%'")
    assert life.import_core(root / "external", root / "hypotheses") == 3  # rebuilt from the files at every start


def test_exploration_lane_is_split_between_active_and_precise_strategies(env):
    """Owner, 2026-11-22: frequent (15m/1h) and rare precise (2h–12h) strategies are tested side
    by side. Autopilot's slow strategies can no longer fill the whole lane."""
    s, reg = env
    s.lifecycle.max_exploration = 4
    life = Lifecycle(s, reg)
    for i in range(4):  # a lane full of slow autopilot strategies (the 21–22.11 situation)
        _strategy(reg, f"slow{i}", "exploration", [f"S{i}/USDT:USDT"], score=1.0 + i, family=f"fam{i}")
        reg.update("strategies", f"slow{i}", {"oos": {"autopilot": True, "timeframe": "6h"}, "stage_since": iso()})
    reg.update("strategies", "slow0", {"live": {"trades": 12, "profit_factor": 1.5}})  # earned its place
    for i in range(3):
        _strategy(reg, f"fast{i}", "exploratory", [f"F{i}/USDT:USDT"], score=0.5 - i * 0.1, family=f"famf{i}")
        reg.update("strategies", f"fast{i}", {"oos": {"timeframe": "1h"}})
    life._fill_slots()
    st = {r["id"]: r["stage"] for r in reg.strategies()}
    lanes = [life.lane(r) for r in reg.strategies(("exploration",))]
    assert lanes.count("active") == 2 and lanes.count("precise") == 2
    assert st["fast0"] == st["fast1"] == "exploration" and st["fast2"] == "exploratory"  # active share is 2 of 4
    assert st["slow0"] == "exploration"  # a sleeve with a live edge is never moved
    assert st["slow1"] == "exploratory" and st["slow2"] == "exploratory" and st["slow3"] == "exploration"
    # a strong precise candidate cannot push the active lane below its share
    _strategy(reg, "slow9", "exploratory", ["S9/USDT:USDT"], score=9.0, family="fam9")
    reg.update("strategies", "slow9", {"oos": {"autopilot": True, "timeframe": "12h"}})
    life._fill_slots()
    assert [life.lane(r) for r in reg.strategies(("exploration",))].count("active") == 2
