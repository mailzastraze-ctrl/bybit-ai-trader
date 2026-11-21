"""Evidence statistics: Newey–West t, anytime-valid forward threshold, beta/alpha, shrinkage,
and the decisions built on them (clean-OOS gate, forward verdict v2, benchmark, readiness,
alpha gate for production, evidence-based learner)."""

from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from helpers import make_trades

from aitrader import context, forward, readiness
from aitrader import evidence as EV
from aitrader.learner import Learner
from aitrader.lifecycle import Lifecycle
from aitrader.registry import Registry
from aitrader.research.validation import Gates, clean_oos, evaluate_gates
from aitrader.settings import Settings
from aitrader.util import iso, utcnow


@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=tmp_path, app_dir=Path(__file__).resolve().parents[1])
    s.ensure_dirs()
    return s, Registry(s.registry_path)


def btc_closes(start="2025-01-01", days=800, seed=7, drift=0.0, vol=0.03) -> dict:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=days, freq="1D", tz="UTC")
    px = 50_000 * np.exp(np.cumsum(rng.normal(drift, vol, days)))
    return {d.strftime("%Y-%m-%d"): float(p) for d, p in zip(idx, px, strict=True)}


# ------------------------------------------------------------------ pure statistics
def test_newey_west_equals_plain_t_on_noise_and_discounts_clustered_days():
    rng = np.random.default_rng(1)
    x = rng.normal(0.1, 1.0, 2000)
    plain = x.mean() / x.std(ddof=1) * np.sqrt(len(x))
    assert EV.newey_west_t(x) == pytest.approx(plain, rel=0.1)
    e = np.zeros(2000)  # AR(1): yesterday's shock carries over – same-direction trades cluster
    for i in range(1, 2000):
        e[i] = 0.7 * e[i - 1] + rng.normal()
    y = 0.1 + e
    plain_y = y.mean() / y.std(ddof=1) * np.sqrt(len(y))
    assert EV.newey_west_t(y) < 0.7 * plain_y


def test_anytime_threshold_values():
    assert EV.anytime_t_boundary(90) == pytest.approx(3.255, abs=1e-3)
    assert EV.anytime_t_boundary(365) == pytest.approx(2.786, abs=1e-3)
    vals = [EV.anytime_t_boundary(n) for n in (90, 180, 365, 730)]
    assert vals == sorted(vals, reverse=True) and min(vals) >= EV.T_FLOOR
    # the price of looking forever: the threshold creeps up again like log n over many years
    assert EV.T_FLOOR < EV.anytime_t_boundary(3650) < 3.0


def test_anytime_threshold_holds_false_works_rate_under_repeated_looks():
    """No edge at all, checked every day for a year. v1 (t ≥ 2 from day 14) declares
    'works' by luck far more often than 5 %; v2 (from day 90, anytime threshold) does not."""
    rng = np.random.default_rng(3)
    paths, days = 3000, 365
    r = rng.normal(0.0, 1.0, (paths, days))
    n = np.arange(1, days + 1)
    cs, cs2 = np.cumsum(r, 1), np.cumsum(r * r, 1)
    sd = np.sqrt(np.maximum(cs2 - cs * cs / n, 1e-12) / np.maximum(n - 1, 1))
    t = cs / n / sd * np.sqrt(n)
    v1 = (t[:, 13:] >= 2.0).any(1).mean()
    bound = np.array([EV.anytime_t_boundary(k) for k in n])
    v2 = (t[:, 89:] >= bound[89:]).any(1).mean()
    assert v1 > 0.12 and v2 <= 0.05, (v1, v2)


def test_alpha_beta_separates_market_from_skill():
    btc = EV.btc_returns(btc_closes(days=300))
    rng = np.random.default_rng(5)
    beta_only = -1.0 * btc  # a short book: profits whenever BTC falls, no skill
    a = EV.alpha_beta(beta_only, btc)
    assert a["beta"] == pytest.approx(-1.0, abs=1e-6) and abs(a["alpha"]) < 1e-9
    skill = pd.Series(0.004 + 0.3 * btc.to_numpy() + rng.normal(0, 0.01, len(btc)), index=btc.index)
    b = EV.alpha_beta(skill, btc)
    assert b["alpha"] > 0 and b["alpha_t"] > 2 and b["beta"] == pytest.approx(0.3, abs=0.1)
    assert EV.alpha_beta(skill.iloc[:3], btc)["alpha"] is None  # too few common days


def test_daily_returns_count_quiet_days_as_zero():
    trades = [{"close_date": "2026-01-01T10:00:00+00:00", "p": 50.0},
              {"close_date": "2026-01-01T20:00:00+00:00", "p": -10.0},
              {"close_date": "2026-01-04T08:00:00+00:00", "p": 20.0}]
    s = EV.daily_returns(trades, 10_000, lambda t: t["p"])
    assert list(s.round(6)) == [0.004, 0.0, 0.0, 0.002]


def test_shrinkage_ranks_a_long_steady_record_above_a_lucky_streak():
    means = {"lucky": 0.03, "steady": 0.004, **{f"n{i}": 0.0 for i in range(10)}}
    ses = {"lucky": 0.02, "steady": 0.0008, **{f"n{i}": 0.003 for i in range(10)}}
    out = EV.shrink(means, ses)
    # similar expected value, very different certainty: the conservative bound decides
    assert out["steady"]["lcb"] > out["lucky"]["lcb"] and out["steady"]["p_pos"] > out["lucky"]["p_pos"]
    assert out["steady"]["p_pos"] > 0.9 and out["lucky"]["shrunk"] < 0.2 * means["lucky"]


# ------------------------------------------------------------------ 1. clean out-of-sample
def _m(**kw):
    oos = {"trades": 120, "profit_factor": 1.6, "sharpe": 1.4, "max_drawdown": 0.08, "total_return": 0.2}
    return {"oos": oos, "stress": {"profit_factor": 1.3}, "wfe": 0.6, "robust_frac": 0.8,
            "mc": {"prob_profit": 0.9}, "dsr": 0.99, "fold_pos": 1.0, **kw}


def test_screener_and_external_configs_cannot_validate_on_data_they_were_chosen_on():
    g = Gates()
    assert evaluate_gates(g, _m())[0] == "validated"
    verdict, gates = evaluate_gates(g, _m(clean_oos=False))
    assert verdict == "exploratory" and not gates["clean_oos"]["pass"]
    assert evaluate_gates(g, _m(clean_oos=True))[0] == "validated"
    assert not clean_oos({"screen": "scr-1"}) and not clean_oos({"external": "owner-x"})
    assert clean_oos({"family": "tsmom"}) and clean_oos({"revalidates": "s1"})


def test_batch_merge_caps_screener_survivors_at_exploratory(tmp_path):
    import json

    from aitrader.research import batch
    oos = {"trades": 150, "profit_factor": 2.0, "sharpe": 2.5, "max_drawdown": 0.05, "total_return": 0.4,
           "daily_sharpe": 0.4, "n_days": 360, "skew": 0.0, "kurtosis": 3.0}
    res = {"oos": oos, "stress": {"profit_factor": 1.8}, "wfe": 0.9, "robust_frac": 1.0, "mc": {"prob_profit": 1.0},
           "fold_pos": 1.0, "params": {}, "pairs": ["BTC/USDT:USDT"]}
    exps = [{"id": "xa", "spec": {"family": "tsmom", "pairs": ["BTC/USDT:USDT"]}, "result": res},
            {"id": "xb", "spec": {"family": "tsmom", "pairs": ["BTC/USDT:USDT"], "screen": "scr-9"}, "result": res}]
    (tmp_path / "results-1.json").write_text(json.dumps({"experiments": exps, "exchange": "bybit"}))
    m = batch.merge([tmp_path], "b1")
    stage = {c["experiment"]: c for c in m["candidates"]}
    assert stage["xb"]["stage"] == "exploratory" and stage["xb"]["oos"]["clean_oos"] is False
    assert not stage["xb"]["gates"]["clean_oos"]["pass"] and "clean_oos" not in stage["xa"]["gates"]


# ------------------------------------------------------------------ 2. forward verdict v2 + benchmark + leaderboard
def _rows(n, edge_top, edge_rest, days, per_day=2, seed=1):
    rng, now, rows = np.random.default_rng(seed), utcnow(), []
    for i in range(n):
        top = i < n // 4
        trades = [[iso(now - timedelta(days=days - d))[:16], float(rng.normal(edge_top if top else edge_rest, 0.002))]
                  for d in range(days) for _ in range(per_day)]
        rows.append({"id": f"x{i:05d}", "score": 10 - i * 0.1, "freeze": iso(now - timedelta(days=days + 1)),
                     "trades": trades, "variant": "v", "family": "tsmom" if i % 2 else "trend_ema"})
    return rows


def test_works_needs_ninety_days_and_the_anytime_threshold():
    early = forward.summarize(_rows(40, 0.0015, -0.0005, days=20))
    assert early["verdict"] == "early_positive" and early["rules"]["final_days"] == 90
    late = forward.summarize(_rows(40, 0.0015, -0.0005, days=120))
    assert late["verdict"] == "works" and late["t_needed"] >= 2.79 and late["top"]["t_daily"] >= late["t_needed"]
    weak = forward.summarize(_rows(40, 0.00012, 0.0, days=120, seed=4))  # positive, but not beyond luck
    assert weak["verdict"] in ("inconclusive", "not_working") and weak["top"]["t_daily"] < weak["t_needed"]
    assert set(late["families"]) == {"tsmom", "trend_ema"}


def test_not_working_needs_ninety_days_too():
    assert forward.summarize(_rows(40, -0.001, 0.0, days=20))["verdict"] == "early_negative"
    assert forward.summarize(_rows(40, -0.001, 0.0, days=100))["verdict"] == "not_working"


def test_benchmark_is_reported_apart_from_the_research_ranking():
    rows = _rows(40, 0.0015, -0.0005, days=120)
    bench = {"id": "benchmark-tsmom-4h-30d", "benchmark": True, "score": 0.0, "freeze": rows[0]["freeze"],
             "family": "tsmom", "trades": [[t[0], 0.0005] for t in rows[0]["trades"]]}
    v = forward.summarize(rows + [bench])
    assert v["benchmark"]["strategies"] == 1 and v["n_strategies"] == 40
    assert v["top"]["strategies"] == 10 and "Benchmark" in v["text"]


def test_leaderboard_prefers_evidence_over_luck():
    now = utcnow()
    f = iso(now - timedelta(days=30))
    lucky = {"id": "lucky", "score": 1, "freeze": f, "trades": [[iso(now)[:16], 0.03]] * 4 + [[iso(now)[:16], -0.01]] * 2}
    rng = np.random.default_rng(2)
    steady = {"id": "steady", "score": 1, "freeze": f, "trades": [[iso(now)[:16], float(rng.normal(0.003, 0.004))] for _ in range(150)]}
    noise = [{"id": f"n{i}", "score": 1, "freeze": f,
              "trades": [[iso(now)[:16], float(rng.normal(0.0, 0.01))] for _ in range(40)]} for i in range(12)]
    best = forward.summarize([lucky, steady, *noise])["best"]
    assert best[0]["id"] == "steady" and best[0]["p_pos"] > 0.9
    assert [b["id"] for b in best].index("lucky") > 0


def test_benchmark_stays_in_the_book_and_its_replication_is_not_research_output(env):
    s, reg = env
    life = Lifecycle(s, reg)
    life.import_external(Path(__file__).resolve().parents[1] / "research" / "external")
    st = reg.one("SELECT * FROM strategies WHERE id='benchmark-tsmom-4h-30d'")
    assert st["oos"]["benchmark"] is True and st["oos"]["timeframe"] == "4h" and st["params"]["lookback"] == 180
    old = iso(utcnow() - timedelta(days=400))
    reg.update("strategies", st["id"], {"created": old, "stage": "retired"})
    fin = iso(utcnow() - timedelta(hours=10))
    reg.upsert("experiments", {"id": "xrep", "created": fin, "family": "tsmom", "status": "done", "finished": fin,
                               "spec": {"family": "tsmom", "pairs": ["BTC/USDT:USDT"], "external": st["id"]},
                               "result": {"params": {"lookback": 180}, "pairs": ["BTC/USDT:USDT"], "score": 9.0}})
    b = forward.book(reg)
    ids = [e["id"] for e in b]
    assert "benchmark-tsmom-4h-30d" in ids and "xrep" not in ids
    assert next(e for e in b if e["id"] == st["id"])["benchmark"] is True


# ------------------------------------------------------------------ 3. readiness
def _prod(reg, sid, since_days):
    since = iso(utcnow() - timedelta(days=since_days))
    reg.upsert("strategies", {"id": sid, "experiment_id": "", "family": "trend_ema", "params": {}, "pairs": ["BTC/USDT:USDT"],
                              "sides": ["long"], "stage": "production", "score": 1, "oos": {"expectancy": 0.004},
                              "gates": {}, "live": {}, "created": since, "updated": since, "stage_since": since, "history": []})


def _beta_trades(reg, sid, start_id, btc: dict, days: int, beta: float, edge: float, equity=10_000.0):
    """One trade a day whose PnL is beta × BTC's daily move plus `edge` (fraction of equity)."""
    rets = EV.btc_returns(btc)
    rets = rets[rets.index >= pd.Timestamp(utcnow() - timedelta(days=days)).normalize()]
    for i, (d, r) in enumerate(rets.items()):
        pnl = (beta * r + edge) * equity
        cd = d + pd.Timedelta(hours=12)
        reg.upsert("live_trades", {"trade_id": start_id + i, "sleeve_id": sid, "pair": "BTC/USDT:USDT", "is_short": int(beta < 0),
                                   "open_date": iso(cd - pd.Timedelta(hours=2)), "close_date": iso(cd), "open_rate": 100,
                                   "close_rate": 101, "profit_ratio": pnl / 1000, "profit_abs": pnl, "exit_reason": "x",
                                   "max_rate": 0, "min_rate": 0, "leverage": 1.0, "stake_amount": 1.0, "raw": {}}, key="trade_id")


def test_readiness_has_daily_and_alpha_checks_that_need_btc_data(env):
    _, reg = env
    _prod(reg, "a", 120)
    r = readiness.evaluate(reg, 10_000)
    assert r["total"] == 10 and {"t_daily", "alpha"} <= {c["id"] for c in r["checks"]}
    btc = btc_closes(start=(utcnow() - timedelta(days=200)).strftime("%Y-%m-%d"), days=200, drift=-0.004)
    _beta_trades(reg, "a", 1, btc, days=110, beta=-1.0, edge=0.0)  # a short book in a falling market
    r = readiness.evaluate(reg, 10_000)
    chk = {c["id"]: c for c in r["checks"]}
    assert not chk["alpha"]["pass"] and "нет данных BTC" in str(chk["alpha"]["value"])
    reg.kv_set("btc_daily", btc)
    chk = {c["id"]: c for c in readiness.evaluate(reg, 10_000)["checks"]}
    assert not chk["alpha"]["pass"], chk["alpha"]  # profitable, but it is all beta


# ------------------------------------------------------------------ 4. lifecycle: no production for pure beta
def _incubating(reg, sid):
    reg.upsert("strategies", {"id": sid, "experiment_id": "", "family": "trend_ema", "params": {}, "pairs": ["BTC/USDT:USDT"],
                              "sides": ["long", "short"], "stage": "incubation", "score": 1.0, "oos": {}, "gates": {},
                              "live": {}, "created": "2020-01-01", "updated": iso(),
                              "stage_since": iso(utcnow() - timedelta(days=10)), "history": []})


def test_production_needs_alpha_not_just_a_rising_market(env):
    s, reg = env
    btc = btc_closes(start=(utcnow() - timedelta(days=120)).strftime("%Y-%m-%d"), days=120, drift=0.006, vol=0.02)
    reg.kv_set("btc_daily", btc)
    _incubating(reg, "beta")
    _beta_trades(reg, "beta", 1, btc, days=40, beta=1.0, edge=-0.0003)  # long BTC minus costs
    _incubating(reg, "skill")
    _beta_trades(reg, "skill", 5000, btc, days=40, beta=0.0, edge=0.002)
    life = Lifecycle(s, reg)
    life.evaluate(10_000)
    stage = {r["id"]: r for r in reg.strategies()}
    assert stage["beta"]["live"]["pnl"] > 0 and stage["beta"]["stage"] == "incubation"
    assert stage["beta"]["live"]["alpha"]["beta"] == pytest.approx(1.0, abs=0.05)
    assert stage["skill"]["stage"] in ("eligible", "production")
    reg.update("strategies", "beta", {"stage_since": iso(utcnow() - timedelta(days=40))})
    life.evaluate(10_000)
    st = reg.one("SELECT stage, history FROM strategies WHERE id='beta'")
    assert st["stage"] == "retired" and "no alpha" in st["history"][-1]["reason"]


def test_production_waits_without_btc_data(env):
    s, reg = env
    btc = btc_closes(start=(utcnow() - timedelta(days=120)).strftime("%Y-%m-%d"), days=120)
    _incubating(reg, "skill")
    _beta_trades(reg, "skill", 1, btc, days=40, beta=0.0, edge=0.002)
    Lifecycle(s, reg).evaluate(10_000)
    assert reg.one("SELECT stage FROM strategies WHERE id='skill'")["stage"] == "incubation"
    # even past the incubation time limit: a data outage is no reason to retire a profitable sleeve
    reg.update("strategies", "skill", {"stage_since": iso(utcnow() - timedelta(days=45))})
    Lifecycle(s, reg).evaluate(10_000)
    assert reg.one("SELECT stage FROM strategies WHERE id='skill'")["stage"] == "incubation"
    reg.kv_set("btc_daily", btc)  # data back → promoted on its alpha
    Lifecycle(s, reg).evaluate(10_000)
    assert reg.one("SELECT stage FROM strategies WHERE id='skill'")["stage"] in ("eligible", "production")


# ------------------------------------------------------------------ 5. learner acts on evidence, not streaks
def _sync(s, reg, sid, pnls, pair="ETH/USDT:USDT", start_id=1):
    trades = make_trades(pnls, tag=sid, pair=pair)
    for i, t in enumerate(trades):
        t["trade_id"] = start_id + i
    Learner(s, reg).sync_trades(trades)


def test_learner_ignores_a_short_losing_streak_but_acts_on_a_real_pattern(env):
    s, reg = env
    for sid in ("a", "b"):
        reg.upsert("strategies", {"id": sid, "experiment_id": "", "family": "trend_ema", "params": {}, "pairs": [],
                                  "sides": ["long", "short"], "stage": "exploration", "score": 1.0, "oos": {}, "gates": {},
                                  "live": {}, "created": "2020-01-01", "updated": iso(), "stage_since": iso(), "history": []})
    _sync(s, reg, "a", [-20, -15, -25, -10, -20, 5], pair="ETH/USDT:USDT")  # v1 excluded ETH after these 6
    Learner(s, reg).analyze_live()
    assert not reg.q("SELECT * FROM learnings WHERE scope='pair'")
    _sync(s, reg, "b", [-20, -18, -22, 4, -19, -21, -20, 3, -18, -22, -20, -19, 2, -21, -20, -18],
          pair="SOL/USDT:USDT", start_id=100)
    Learner(s, reg).analyze_live()
    pairs = [r["adjustment"]["exclude_pair"] for r in reg.q("SELECT * FROM learnings WHERE scope='pair'")]
    assert pairs == ["SOL/USDT:USDT"]


# ------------------------------------------------------------------ 6. BTC daily candles for the market factor
def test_btc_daily_candles_are_fetched_into_the_registry(env):
    _, reg = env
    day = 86_400_000
    today = (int(utcnow().timestamp() * 1000) // day) * day
    rows = [[str(today - k * day), "1", "1", "1", str(100 + k), "1", "1"] for k in range(5)]  # newest first

    def fake_get(url):
        if "kline" in url:
            return {"result": {"list": rows}}
        raise OSError("offline")

    context.refresh(reg, get=fake_get)
    closes = reg.kv_get("btc_daily")
    assert len(closes) == 4 and list(closes) == sorted(closes)  # today's open candle excluded
    assert closes[min(closes)] == 104.0


def test_broken_trade_data_never_breaks_the_manager_loop(env):
    s, reg = env
    reg.kv_set("btc_daily", btc_closes(start=(utcnow() - timedelta(days=60)).strftime("%Y-%m-%d"), days=60))
    _incubating(reg, "odd")
    reg.upsert("live_trades", {"trade_id": 1, "sleeve_id": "odd", "pair": "BTC/USDT:USDT", "is_short": 0,
                               "open_date": "garbage", "close_date": "not-a-date", "open_rate": 100, "close_rate": 101,
                               "profit_ratio": 0.01, "profit_abs": 10.0, "exit_reason": "x", "max_rate": 0, "min_rate": 0,
                               "leverage": 1.0, "stake_amount": 1.0, "raw": {}}, key="trade_id")
    Lifecycle(s, reg).evaluate(10_000)  # must not raise
    st = reg.one("SELECT stage, live FROM strategies WHERE id='odd'")
    assert st["stage"] == "incubation" and st["live"]["alpha"]["alpha"] is None
    readiness.evaluate(reg, 10_000)  # must not raise either


# ------------------------------------------------------------------ 7. forward book keeps candidates (longitudinal)
def test_forward_book_keeps_candidates_and_promising_strategies_for_their_whole_life(env):
    _, reg = env
    now = utcnow()

    def exp(eid, hours_ago, verdict, score):
        fin = iso(now - timedelta(hours=hours_ago))
        reg.upsert("experiments", {"id": eid, "created": fin, "family": "tsmom", "status": "done", "finished": fin,
                                   "spec": {"family": "tsmom", "pairs": ["BTC/USDT:USDT"]},
                                   "result": {"params": {"lookback": 200}, "pairs": ["BTC/USDT:USDT"], "score": score,
                                              "verdict": verdict, "oos": {"profit_factor": 1.2, "trades": 40}}})
    for i in range(20):  # candidates from two weeks ago
        exp(f"xc{i:03d}", 300 + i, "exploratory", 1.0 + i / 100)
    exp("xpromise", 400, "rejected", 0.0)  # rejected in research, but doing well forward
    for i in range(300):  # a flood of newer, rejected experiments
        exp(f"xr{i:03d}", i, "rejected", 0.0)
    reg.kv_set("forward", {"best": [{"id": "xpromise", "p_pos": 0.93, "trades": 25}]})
    b = forward.book(reg)
    ids = [e["id"] for e in b]
    assert len(b) == forward.BOOK_LIMIT
    assert all(f"xc{i:03d}" in ids for i in range(20)) and "xpromise" in ids
    assert ids[0] == "xpromise" and ids[1] == "xc019"  # promising first, then candidates by score
    assert "xr000" in ids and "xr299" not in ids  # the rest of the room goes to the newest experiments


def test_versus_benchmark_gives_direction_with_uncertainty():
    now = utcnow()
    days = [iso(now - timedelta(days=d))[:16] for d in range(30)]
    rng = np.random.default_rng(8)
    top = [{"id": f"t{i}", "trades": [[d, float(rng.normal(0.003, 0.002))] for d in days]} for i in range(4)]
    bench = [{"id": "b", "trades": [[d, float(rng.normal(0.0, 0.002))] for d in days]}]
    v = forward.versus(top, bench)
    assert v["days"] == 30 and v["p_top_better"] > 0.95 and v["top_pct"] > v["bench_pct"]
    assert forward.versus(top, [{"id": "b", "trades": [[days[0], 0.001]]}], min_days=40) is None


# ------------------------------------------------------------------ 8. TSMOM is also searched on 4h
def test_tsmom_is_searched_on_4h_half_of_the_time(env):
    from aitrader.research.generator import Generator
    s, reg = env
    g = Generator(s, reg, seed=3)
    tfs = [g.next_spec(["BTC/USDT:USDT", "ETH/USDT:USDT"], family="tsmom")["timeframe"] for _ in range(200)]
    assert set(tfs) == {"1h", "4h"} and 70 < tfs.count("4h") < 130
    others = {g.next_spec(["BTC/USDT:USDT"], family="trend_ema")["timeframe"] for _ in range(50)}
    assert "4h" not in others


# ------------------------------------------------------------------ 9. storage: weeks without filling the volume
def test_storage_slims_old_rejected_research_and_trims_logs(env, tmp_path):
    from aitrader import storage
    from aitrader.manager import housekeeping
    s, reg = env
    old, new = iso(utcnow() - timedelta(days=5)), iso(utcnow() - timedelta(hours=5))
    fat = {"params": {"a": 1}, "pairs": ["BTC/USDT:USDT"], "score": 0.0, "verdict": "rejected",
           "oos": {"daily_sharpe": -0.05, "trades": 30, "profit_factor": 0.8}, "gates": {"trades": {"pass": True}},
           "curve": [[i, 1.0] for i in range(400)], "pair_stats": {"BTC": {"pnl": 1}}, "exit_reasons": {"x": 3},
           "folds": [{"fold": 0, "test": "a-b", "params": {"a": 1}, "oos": {"total_return": 0.01, "trades": 9}}]}
    for eid, fin, verdict in (("xold", old, "rejected"), ("xnew", new, "rejected"), ("xcand", old, "exploratory")):
        reg.upsert("experiments", {"id": eid, "created": fin, "family": "tsmom", "status": "done", "finished": fin,
                                   "spec": {"family": "tsmom"}, "result": {**fat, "verdict": verdict}})
    logs = tmp_path / "logs"
    logs.mkdir()
    for name in ("freqtrade.log", "freqtrade.log.1", "freqtrade.log.2", "freqtrade.log.3", "freqtrade.log.10"):
        (logs / name).write_text("x")
    st = storage.maintain(reg, tmp_path, logs)
    assert st["slimmed"] == 1 and st["logs_removed"] == 2 and st["total_mb"] > 0 and reg.kv_get("disk")["free_mb"] >= 0
    assert sorted(p.name for p in logs.iterdir()) == ["freqtrade.log", "freqtrade.log.1", "freqtrade.log.2"]
    res = {r["id"]: r["result"] for r in reg.q("SELECT id, result FROM experiments")}
    assert res["xold"]["slim"] and "curve" not in res["xold"] and res["xold"]["oos"]["daily_sharpe"] == -0.05
    assert res["xold"]["folds"] == [{"fold": 0, "test": "a-b", "oos": {"total_return": 0.01}}]  # persistence + cards
    assert "curve" in res["xnew"] and "curve" in res["xcand"]  # recent and candidate results stay whole
    # everything later readers need still works on slimmed rows
    from aitrader import lab
    assert lab.build_state(s, reg)["family_stats"]["tsmom"][0] == 3
    housekeeping(reg, s)  # the manager path runs it without raising


def test_storage_slims_harder_when_the_disk_is_almost_full(env, tmp_path, monkeypatch):
    from aitrader import storage
    _, reg = env
    fin = iso(utcnow() - timedelta(hours=30))
    reg.upsert("experiments", {"id": "x1", "created": fin, "family": "tsmom", "status": "done", "finished": fin,
                               "spec": {}, "result": {"verdict": "rejected", "curve": [1, 2], "oos": {}}})
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda p: type("U", (), {"total": 1000, "used": 900, "free": 100})())
    st = storage.maintain(reg, tmp_path, None)
    assert st["low"] and st["slimmed"] == 1
    assert any("disk almost full" in e["message"] for e in reg.q("SELECT message FROM events"))


def test_learner_needs_eight_recent_experiments_for_a_research_pattern(env):
    s, reg = env
    def exp(i):
        fin = iso(utcnow() - timedelta(hours=i))
        reg.upsert("experiments", {"id": f"xg{i}", "created": fin, "family": "turtle", "status": "done", "finished": fin,
                                   "spec": {"family": "turtle"},
                                   "result": {"score": 0, "verdict": "rejected", "gates": {"max_drawdown": {"pass": False}}}})
    for i in range(5):
        exp(i)
    Learner(s, reg).learn_from_research()
    assert not reg.q("SELECT * FROM learnings WHERE scope='research'")
    for i in range(5, 9):
        exp(i)
    Learner(s, reg).learn_from_research()
    assert reg.q("SELECT * FROM learnings WHERE scope='research'")


# ------------------------------------------------------------------ 10. rotation by evidence + all proven at once
def _st(reg, sid, stage, pairs, score=1.0, family="tsmom", days=1.0, live=None, oos=None):
    since = iso(utcnow() - timedelta(days=days))
    reg.upsert("strategies", {"id": sid, "experiment_id": "", "family": family, "params": {}, "pairs": pairs,
                              "sides": ["long", "short"], "stage": stage, "score": score, "oos": oos or {}, "gates": {},
                              "live": live or {}, "created": since, "updated": since, "stage_since": since, "history": []})


def test_rotation_by_evidence_moves_idle_sleeves_out_for_stronger_candidates(env):
    s, reg = env
    s.lifecycle.max_exploration = 3
    life = Lifecycle(s, reg)
    _st(reg, "idle", "exploration", ["SOL/USDT:USDT"], score=0.9, days=10, live={"trades": 1})  # a week+, 1 trade
    _st(reg, "young", "exploration", ["ETH/USDT:USDT"], score=0.1, days=2, live={"trades": 0})  # too new to judge
    _st(reg, "earned", "exploration", ["XRP/USDT:USDT"], score=0.1, days=15, live={"trades": 12, "profit_factor": 1.5})
    _st(reg, "fw-strong", "exploratory", ["DOGE/USDT:USDT"], score=0.5, family="macd_cross",
        oos={"forward": {"trades": 25, "pf": 1.6}})
    _st(reg, "weak", "exploratory", ["ADA/USDT:USDT"], score=0.05, family="ema_cross")
    life._fill_slots()
    st = {r["id"]: r for r in reg.strategies()}
    assert st["fw-strong"]["stage"] == "exploration"  # forward-proven took the idle slot
    assert st["idle"]["stage"] == "exploratory" and "rotated out" in st["idle"]["history"][-1]["reason"]  # back in queue
    assert st["young"]["stage"] == "exploration" and st["earned"]["stage"] == "exploration"
    assert st["weak"]["stage"] == "exploratory"  # a weaker candidate does not push anyone out
    assert life.evidence_rank(st["fw-strong"])[0] == 3 and life.evidence_rank(st["weak"])[0] == 1


def test_many_proven_strategies_trade_at_once_on_their_own_coins(env):
    s, reg = env
    life = Lifecycle(s, reg)
    coins = [f"C{i}/USDT:USDT" for i in range(18)]
    for i, c in enumerate(coins):  # 18 proven TSMOM variants, each on its own coin
        _st(reg, f"p{i:02d}", "validated", [c], score=1.0 + i / 100, family="tsmom")
    life._fill_slots()
    inc = reg.strategies(("incubation",))
    assert len(inc) == 18  # no 8-slot or 6-per-family ceiling: one family on different coins is fine
    man = life.build_manifest([], set(), False)
    assert {p for sl in man.sleeves for p in sl.pairs} == set(coins)
    assert all(abs(sl.risk - s.lifecycle.risk_incubation) < 1e-9 for sl in man.sleeves)  # budget not exceeded → full size
    for i in range(18):
        reg.update("strategies", f"p{i:02d}", {"stage": "production"})
    man = life.build_manifest([], set(), False)
    k = reg.kv_get("proven_scale")["scale"]
    assert k < 1 and all(sl.risk == pytest.approx(s.lifecycle.risk_production * k, rel=2e-3) for sl in man.sleeves)
    # with half of the coins in a trade the open risk stays within the proven budget
    assert 0.5 * sum(sl.risk * len(sl.pairs) for sl in man.sleeves) <= s.lifecycle.proven_risk_budget + 1e-4  # 6-digit rounding
    # but two of one family on the same coin is the limit
    _st(reg, "dup1", "validated", [coins[0]], family="tsmom")
    _st(reg, "dup2", "validated", [coins[0]], family="tsmom")
    life._fill_slots()
    stages = {r["id"]: r["stage"] for r in reg.strategies()}
    assert sorted((stages["dup1"], stages["dup2"])) == ["incubation", "validated"]


# ------------------------------------------------------------------ 11. research alpha gate, daily loss limit
def test_validation_needs_oos_alpha_over_btc_but_exploration_does_not():
    g = Gates()
    assert evaluate_gates(g, _m(alpha=0.002, alpha_t=2.5))[0] == "validated"
    v, gates = evaluate_gates(g, _m(alpha=0.0001, alpha_t=0.3))  # profitable, but the market explains it
    assert v == "exploratory" and not gates["market_alpha"]["pass"]
    assert "market_alpha" not in evaluate_gates(g, _m())[1]  # no BTC data → gate not applied
    assert evaluate_gates(g, _m(alpha=-0.001, alpha_t=1.5))[0] == "exploratory"


def test_oos_market_split_reads_btc_candles(env):
    pytest.importorskip("pyarrow")  # feather files (present in the Freqtrade image)
    from aitrader.families import MARKET_PAIR
    from aitrader.research.pipeline import Pipeline, pair_file
    s, reg = env
    fn = pair_file(s, MARKET_PAIR)
    fn.parent.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range("2025-01-01", periods=24 * 200, freq="1h", tz="UTC")
    rng = np.random.default_rng(4)
    px = 50_000 * np.exp(np.cumsum(rng.normal(-0.0004, 0.006, len(idx))))  # a falling market
    pd.DataFrame({"date": idx, "open": px, "high": px, "low": px, "close": px, "volume": 1.0}).to_feather(fn)
    daily = pd.Series(px, index=idx).resample("1D").last()
    rets = np.log(daily).diff().dropna()
    shorts = [{"close_date": (d + pd.Timedelta(hours=12)).isoformat(), "profit_abs": float(-r * 10_000)} for d, r in rets.items()]
    pipe = Pipeline(s, reg, runner=object())
    m = pipe._oos_market_split(shorts, idx[0], idx[-1])
    assert m["beta"] == pytest.approx(-1.0, abs=0.05) and abs(m["alpha_t"]) < 1.0  # all of it is beta
    assert pipe._oos_market_split([], idx[0], idx[-1]) is None


def test_daily_loss_limit_pauses_entries_until_the_next_utc_day(env):
    from aitrader.manager import daily_stop
    _, reg = env
    assert daily_stop(reg, 10_000, 0.03) is False  # day's first reading
    assert daily_stop(reg, 9_800, 0.03) is False   # −2 %
    assert daily_stop(reg, 9_690, 0.03) is False   # −3.1 % once: could be a glitchy balance read
    assert daily_stop(reg, 9_980, 0.03) is False   # it was: back to normal, counter reset
    assert daily_stop(reg, 9_690, 0.03) is False
    assert daily_stop(reg, 9_680, 0.03) is True    # −3 % twice in a row → paused
    assert daily_stop(reg, 9_950, 0.03) is True    # stays paused for the rest of the day
    assert any("DAILY LOSS LIMIT" in e["message"] for e in reg.q("SELECT message FROM events"))
    reg.kv_set("day_open", {"day": "2000-01-01", "equity": 10_000, "hit": True})
    assert daily_stop(reg, 9_000, 0.03) is False   # a new day starts from its own first reading
