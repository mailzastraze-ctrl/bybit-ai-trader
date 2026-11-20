"""Strategy cards for the control room ("Стратегии" tab): every strategy the company has –
trading on demo, candidates, screener survivors, rejected – explained in plain Russian,
with its unseen-data result, equity curve and why it is where it is."""

from __future__ import annotations

from aitrader.families import FAMILIES
from aitrader.registry import Registry


def _f(x, nd=2):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "?"
    return str(int(v)) if v == int(v) else f"{v:.{nd}f}".rstrip("0").rstrip(".")


TITLE = {
    "trend_ema": "EMA-тренд + откат", "meanrev_bb": "Боллинджер: возврат (с фильтрами)", "donchian_breakout": "Пробой канала",
    "squeeze_momentum": "Сжатие волатильности → импульс", "tsmom": "Импульс за несколько дней", "funding_reversal":
    "Перекос фандинга", "zscore_revert": "Z-score: возврат к среднему", "supertrend": "SuperTrend",
    "macd_cross": "MACD", "adx_di": "ADX + DI (сила тренда)", "hull_turn": "Разворот Hull MA", "rsi_revert": "RSI: возврат к среднему",
    "stoch_cross": "Стохастик", "ema_cross": "Пересечение EMA", "bb_revert": "Полосы Боллинджера: возврат", "turtle": "Пробой Дончиана (черепахи)",
    "rel_strength": "Сила монеты относительно BTC",
}


def idea(family: str, p: dict) -> str:
    g = lambda k: _f(p.get(k))  # noqa: E731
    t = {
        "zscore_revert": f"Считает, на сколько стандартных отклонений цена ушла от среднего за {g('window')} свечей. "
                         f"Ниже −{g('z_entry')}σ — покупка в расчёте на возврат, выход при −{g('z_exit')}σ. Выше +{g('z_entry')}σ — шорт.",
        "supertrend": f"Следует за трендом: вход при смене направления SuperTrend (ATR {g('st_len')}, множитель {g('st_mult')}), "
                      "выход — при обратной смене.",
        "macd_cross": f"Лонг, когда MACD ({g('macd_fast')}/{_f(float(p.get('macd_fast', 0)) + float(p.get('macd_gap', 0)))}, "
                      f"сигнальная {g('macd_signal')}) пересекает сигнальную линию снизу вверх, шорт — сверху вниз"
                      + (" (только по стороне нуля)." if int(float(p.get("macd_zero", 0))) else "."),
        "adx_di": f"Вход при пересечении +DI/−DI (период {g('di_len')}), только если ADX выше {g('adx_thr')} — тренд достаточно сильный.",
        "hull_turn": f"Лонг, когда скользящая Hull ({g('hma_len')}) разворачивается вверх, шорт — когда вниз. Быстрый тренд с малой задержкой.",
        "rsi_revert": f"Лонг, когда RSI({g('rsi_len')}) выходит вверх из зоны ниже {g('rsi_lower')}; выход при RSI ≥ "
                      f"{_f(50 + float(p.get('rsi_exit', 0)))}. Шорт зеркально"
                      + (f", только по тренду SMA {g('rsi_trend')}." if float(p.get("rsi_trend", 0)) >= 20 else "."),
        "stoch_cross": f"Лонг при пересечении %K выше %D в зоне перепроданности (< {_f(float(p.get('stoch_lo', 20)) + 10)}), "
                       "шорт — в зоне перекупленности; выход по обратному пересечению.",
        "ema_cross": f"Лонг, когда EMA {g('ema_fast')} пересекает EMA {g('ema_slow')} снизу вверх, шорт — сверху вниз"
                     + (f", только по тренду EMA {g('ema_trend')}." if float(p.get("ema_trend", 0)) >= 20 else "."),
        "bb_revert": f"Лонг, когда цена закрывается ниже нижней полосы Боллинджера ({g('br_len')}, {g('br_mult')}σ); "
                     "выход у средней линии. Шорт — от верхней полосы.",
        "turtle": f"Лонг на пробое максимума за {g('tt_entry')} свечей, выход при пробое минимума за {g('tt_exit')} (система «черепах»). "
                  "Шорт зеркально.",
        "rel_strength": f"Сравнивает монету с биткоином: если за {g('rs_len')} свечей монета обогнала BTC сильнее обычного "
                        f"(более {g('rs_z')}σ), покупает её; если отстала — шорт. Выход, когда относительный рывок угасает.",
        "trend_ema": f"Торгует по тренду: EMA {g('fast')}/{g('slow')} при ADX > {g('adx_min')}, входы на пересечении и откатах RSI.",
        "meanrev_bb": f"Против выхода за полосы Боллинджера ({g('bb_len')}, {g('bb_k')}σ) при экстремальном RSI и только в боковике (ADX < {g('adx_max')}).",
        "donchian_breakout": "Вход на пробое канала Дончиана с подтверждением, выход по противоположной границе.",
        "squeeze_momentum": "Ждёт сжатия волатильности (Боллинджер внутри Кельтнера) и входит по направлению импульса после выхода.",
        "tsmom": f"Импульс в единицах волатильности за {g('lookback')} свечей: торгует его знак с подтверждением.",
        "funding_reversal": "Когда фандинг экстремален, одна сторона перегружена — вход против неё после подтверждения ценой.",
    }.get(family)
    return t or (FAMILIES[family].description if family in FAMILIES else family)


def exits_text(p: dict) -> str:
    tp = float(p.get("tp_rr", 5) or 5)
    tr_rr, tr_atr = float(p.get("trail_rr", 3) or 3), p.get("trail_atr")
    parts = [f"стоп {_f(p.get('sl_atr'))}×ATR", "без тейка" if tp >= 5 else f"тейк {_f(tp)}R",
             "трейлинг от входа" if tr_rr <= 0.5 else f"трейлинг {_f(tr_atr)}×ATR после +{_f(tr_rr)}R"]
    if float(p.get("lock_frac", 0) or 0) > 0:
        parts.append(f"фиксация {int(float(p['lock_frac']) * 100)}% прибыли после +{_f(p.get('lock_rr'))}R")
    return ", ".join(parts)


GATE_RU = {"trades": "мало сделок", "profit_factor": "низкий profit factor", "sharpe": "низкий Шарп", "max_drawdown": "большая просадка",
           "stress_pf": "не выдерживает двойные комиссии", "wfe": "на новых данных сильно хуже, чем на обучении",
           "robustness": "неустойчива к малым изменениям параметров", "monte_carlo": "Монте-Карло: высокий риск",
           "deflated_sharpe": "результат может быть удачей перебора", "fold_consistency": "прибыльна не во всех окнах"}

STATUS_RU = {"production": "Торгует (основная)", "eligible": "Торгует (доказала себя)", "incubation": "Торгует (испытание)",
             "exploration": "Торгует на демо (разведка)", "closing": "Закрывает позицию", "exploratory": "Кандидат",
             "validated": "Прошла все проверки", "rejected": "Отсеяна", "retired": "Снята с торговли"}


def _card(kind: str, st: dict, res: dict | None = None) -> dict:
    fam = st.get("family")
    params = (FAMILIES[fam].normalize(st.get("params")) if fam in FAMILIES else st.get("params")) or {}
    oos = (res or {}).get("oos") or st.get("oos") or {}
    gates = (res or {}).get("gates") or st.get("gates") or {}
    failed = [GATE_RU.get(k, k) for k, v in gates.items() if isinstance(v, dict) and not v.get("pass")]
    tf = (res or {}).get("timeframe") or (st.get("oos") or {}).get("timeframe") or "1h"
    return {"id": st["id"], "kind": kind, "family": fam, "title": TITLE.get(fam, fam), "idea": idea(fam, params),
            "exits": exits_text(params), "timeframe": tf, "pairs": st.get("pairs") or [], "stage": st.get("stage"),
            "status": STATUS_RU.get(st.get("stage"), st.get("stage")), "params": {k: v for k, v in params.items()
                                                                                  if k in {p.name for p in FAMILIES[fam].entry_params}} if fam in FAMILIES else params,
            "oos": {k: oos.get(k) for k in ("trades", "profit_factor", "sharpe", "max_drawdown", "total_return", "win_rate",
                                            "curve_r2", "last90_return", "pos_months")},
            "curve": (res or {}).get("curve") or [], "folds": [{"test": f.get("test"), "ret": (f.get("oos") or {}).get("total_return"),
                                                                 "trades": (f.get("oos") or {}).get("trades")}
                                                                for f in ((res or {}).get("folds") or [])],
            "why_not": failed, "live": st.get("live") or {}, "external": bool((st.get("oos") or {}).get("external")),
            "claimed": (st.get("oos") or {}).get("claimed"), "updated": st.get("updated") or st.get("created")}


def build(reg: Registry, limit: int = 120) -> dict:
    cards, seen_exp = [], set()
    exp = {r["id"]: r for r in reg.q("SELECT id, result FROM experiments WHERE status='done'")}
    for st in reg.q("SELECT * FROM strategies WHERE stage != 'retired' OR updated >= date('now','-7 day') "
                    "ORDER BY updated DESC LIMIT ?", (limit,)):
        res = (exp.get(st.get("experiment_id") or "") or {}).get("result")
        seen_exp.add(st.get("experiment_id"))
        kind = "trading" if st["stage"] in ("production", "eligible", "incubation", "exploration", "closing") else \
            "candidate" if st["stage"] in ("exploratory", "validated") else "rejected"
        cards.append(_card(kind, st, res))
    # finished experiments that never became a strategy record (most rejected ones)
    for r in reg.q("SELECT id, family, spec, result, finished FROM experiments WHERE status='done' "
                   "ORDER BY finished DESC LIMIT ?", (limit,)):
        if r["id"] in seen_exp or not isinstance(r.get("result"), dict):
            continue
        res, spec = r["result"], r.get("spec") or {}
        st = {"id": r["id"], "family": r["family"], "params": res.get("params") or {}, "pairs": res.get("pairs") or spec.get("pairs"),
              "stage": res.get("verdict") if res.get("verdict") != "rejected" else "rejected", "updated": r.get("finished"),
              "oos": {"timeframe": res.get("timeframe") or spec.get("timeframe")}}
        cards.append(_card("rejected" if res.get("verdict") == "rejected" else "candidate", st, res))
    sc = reg.kv_get("screen") or {}
    for x in sc.get("top") or []:
        fam = x.get("family")
        if fam not in FAMILIES:
            continue
        from aitrader.research.screen import to_params
        params = to_params(x) or {}
        b = x.get("B") or {}
        card = _card("screen", {"id": x["id"], "family": fam, "params": params, "pairs": [x.get("pair")], "stage": "exploratory",
                                "updated": sc.get("ts"), "oos": {"timeframe": x.get("timeframe")}},
                     {"oos": {"trades": b.get("trades"), "profit_factor": b.get("pf"), "sharpe": b.get("sharpe"),
                              "max_drawdown": (b.get("dd") or 0) / 100, "total_return": (b.get("net") or 0) / 100,
                              "win_rate": (b.get("win") or 0) / 100, "curve_r2": x.get("r2"),
                              "last90_return": (x.get("last90") or 0) / 100},
                      "timeframe": x.get("timeframe"),
                      "curve": [[str(t)[:10] if isinstance(t, str) else t, v] for t, v in (x.get("curve") or [])]})
        card["status"] = "Скринер: выжила на невиданных данных"
        cards.append(card)
    order = {"trading": 0, "candidate": 1, "screen": 2, "rejected": 3}
    cards.sort(key=lambda c: (order.get(c["kind"], 9), -(c["oos"].get("profit_factor") or 0)))
    return {"cards": cards, "counts": {k: sum(1 for c in cards if c["kind"] == k) for k in order}}
