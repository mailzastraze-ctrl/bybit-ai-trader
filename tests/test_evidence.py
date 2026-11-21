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
