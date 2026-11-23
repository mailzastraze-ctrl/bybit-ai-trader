"""TradFi lane: gold and the S&P 500 as Bybit USDT perpetuals, next to the crypto book.

Owner's request of 23.11.2026 (a ChatGPT recommendation, reviewed): trade gold and the S&P 500 in
the same bot, with the same safety rules, as an independent universe.

Instruments (checked 23.11.2026; Bybit "TradFi" perpetuals, USDT-margined linear contracts):
  * ``XAU/USDT:USDT`` – gold (XAU/USD), listed in spring 2026;
  * ``SPY/USDT:USDT`` – the S&P 500 through the SPDR S&P 500 ETF perpetual, listed in May 2026.
  * ``SPX/USDT:USDT`` is **not** the S&P 500: on Bybit it is the SPX6900 memecoin. The
    recommendation named SPXUSDT; trading it as "S&P 500" would have been a crypto memecoin bet.
    It is never part of this lane (`NOT_TRADFI`).

Whether the demo account can trade them is not assumed: the live bot is the judge. The manager
puts the lane's pairs on the pairlist; Freqtrade (ccxt) keeps a pair on its whitelist only if
the exchange lists it as an active USDT linear contract. `availability` reads that back.

The underlying markets are not open 24/7 while the perpetuals are. Prices outside the
underlying session are set by perpetual traders alone (thin, stale index), so new entries are
only taken while the underlying market is open (`session_open`, `gate_entries`). Exits and the
exchange stop work around the clock.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")

INSTRUMENTS: dict[str, dict] = {
    "XAU/USDT:USDT": {"key": "gold", "name": "Золото (XAU/USD)", "symbol": "XAUUSDT", "session": "gold",
                      "peer": "SPY/USDT:USDT"},
    "SPY/USDT:USDT": {"key": "sp500", "name": "S&P 500 (SPDR S&P 500 ETF, SPY)", "symbol": "SPYUSDT",
                      "session": "nyse", "peer": "XAU/USDT:USDT"},
}
TRADFI_PAIRS: tuple[str, ...] = tuple(INSTRUMENTS)
# look-alikes that must never be treated as TradFi
NOT_TRADFI: dict[str, str] = {"SPX/USDT:USDT": "SPX6900 – memecoin, not the S&P 500 index"}

# NYSE holidays and early closes (13:00 ET), nyse.com "Holidays & Trading Hours" (2025–2027).
# After the last listed year only weekends are known: extend the list every December.
NYSE_HOLIDAYS = frozenset(date.fromisoformat(d) for d in (
    "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19",
    "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
    "2027-09-06", "2027-11-25", "2027-12-24",
))
NYSE_EARLY_CLOSE = frozenset(date.fromisoformat(d) for d in (
    "2025-07-03", "2025-11-28", "2025-12-24", "2026-11-27", "2026-12-24", "2027-11-26",
))
CALENDAR_UNTIL = date(2027, 12, 31)
# gold (CME Globex / OTC spot) is closed on these New York dates as a whole
GOLD_HOLIDAYS = frozenset(date.fromisoformat(d) for d in (
    "2025-01-01", "2025-04-18", "2025-12-25", "2026-01-01", "2026-04-03", "2026-12-25",
    "2027-01-01", "2027-03-26", "2027-12-24", "2027-12-25",
))


# ---------------------------------------------------------------------------- instruments
def is_tradfi(pair: str | None) -> bool:
    return bool(pair) and pair in INSTRUMENTS


def peer_of(pair: str, pairs: list[str] | None = None) -> str | None:
    """The other instrument of a two-asset rotation: another TradFi pair of the sleeve, else the
    instrument's default peer."""
    for p in pairs or []:
        if p != pair and is_tradfi(p):
            return p
    return (INSTRUMENTS.get(pair) or {}).get("peer")


# ---------------------------------------------------------------------------- sessions
def _ny(times) -> pd.Series:
    t = pd.to_datetime(pd.Series(times), utc=True)
    return t.dt.tz_convert(NY)


def session_open(times, pair: str) -> pd.Series:
    """True where the underlying market of `pair` is open at that moment (vectorised, UTC in).

    * S&P 500 (NYSE regular session): 09:30–16:00 New York time Mon–Fri, 13:00 on early-close
      days, closed on NYSE holidays.
    * Gold (CME Globex hours): Sunday 18:00 → Friday 17:00 New York time with a daily break
      17:00–18:00, closed on Good Friday, Christmas and New Year's Day.
    Crypto pairs: always open."""
    s = pd.Series(times)
    kind = (INSTRUMENTS.get(pair) or {}).get("session")
    if kind is None:
        return pd.Series(True, index=s.index)
    loc = _ny(s)
    wd = loc.dt.weekday.to_numpy()
    minutes = (loc.dt.hour * 60 + loc.dt.minute).to_numpy()
    day = loc.dt.date.to_numpy()
    if kind == "nyse":
        close = np.where(np.isin(day, list(NYSE_EARLY_CLOSE)), 13 * 60, 16 * 60)
        ok = (wd < 5) & (minutes >= 9 * 60 + 30) & (minutes < close) & ~np.isin(day, list(NYSE_HOLIDAYS))
    elif kind == "gold":
        brk = (minutes >= 17 * 60) & (minutes < 18 * 60)
        ok = ~brk & (wd != 5)                       # no Saturday, daily maintenance break
        ok &= ~((wd == 6) & (minutes < 18 * 60))    # Sunday opens at 18:00
        ok &= ~((wd == 4) & (minutes >= 17 * 60))   # Friday closes at 17:00
        # a holiday closes the session that would run on that New York date
        ok &= ~np.isin(day, list(GOLD_HOLIDAYS))
    else:
        ok = np.ones(len(s), dtype=bool)
    return pd.Series(ok, index=s.index)


def is_open_now(pair: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    return bool(session_open(pd.Series([pd.Timestamp(now)]), pair).iloc[0])


def gate_entries(res: pd.DataFrame, pair: str) -> pd.DataFrame:
    """New entries only while the underlying market is open, judged at each candle's decision
    time (its close). A signal raised while the market was closed is carried to the first open
    decision after it – unless the strategy's own exit signal for that side is on by then (the
    setup is gone). Exits are never gated. Identical in backtests and live (pure function of the
    candle times). Crypto pairs pass unchanged."""
    if not is_tradfi(pair) or res is None or res.empty or "date" not in res:
        return res
    from aitrader.context import decision_times
    op = session_open(decision_times(res), pair).to_numpy()
    out = res.copy()
    block = np.concatenate([[0], np.cumsum(op)[:-1]])  # closed bars belong to the next open bar
    for sig, ex in (("long_sig", "exit_long_sig"), ("short_sig", "exit_short_sig")):
        s = out[sig].fillna(False).astype(bool)
        carried = s.groupby(block).cummax().to_numpy()
        stop = out[ex].fillna(False).astype(bool).to_numpy() if ex in out else np.zeros(len(out), bool)
        out[sig] = op & carried & (s.to_numpy() | ~stop)
    return out


def next_open(pair: str, now: datetime | None = None, horizon_h: int = 24 * 5) -> datetime | None:
    """First quarter hour at which the underlying is open again (for the control room)."""
    now = pd.Timestamp(now or datetime.now(UTC)).floor("15min")
    ts = pd.Series(pd.date_range(now, periods=horizon_h * 4, freq="15min"))
    op = session_open(ts, pair).to_numpy()
    return ts[op].iloc[0].to_pydatetime() if op.any() else None


# ---------------------------------------------------------------------------- availability
def availability(configured: list[str], whitelist: list[str] | None) -> dict[str, bool | None]:
    """Is each configured instrument tradable on the account? Freqtrade keeps a pair on its
    whitelist only if the exchange (ccxt markets) lists it as an active USDT linear contract;
    None = not known yet (the bot did not answer)."""
    if whitelist is None:
        return {p: None for p in configured}
    wl = set(whitelist)
    return {p: p in wl for p in configured}


# ---------------------------------------------------------------------------- correlation
def _corr(a: list[float], b: list[float], min_n: int = 48) -> float | None:
    n = min(len(a), len(b))
    if n < min_n:
        return None
    x, y = np.asarray(a[-n:], float), np.asarray(b[-n:], float)
    if np.nanstd(x) == 0 or np.nanstd(y) == 0:
        return None
    c = float(np.corrcoef(x, y)[0, 1])
    return c if c == c else None


def corr_scale(rho: float | None) -> float:
    """Risk scale for a TradFi entry that moves with the crypto book: 1 / (1 + ρ⁺) against BTC,
    floor 0.5. Only ever shrinks the size (an unknown correlation keeps 1.0: the account and side
    caps already count every TradFi trade in full)."""
    if rho is None or rho != rho or rho <= 0:
        return 1.0
    return round(max(0.5, 1.0 / (1.0 + rho)), 3)


def correlations(rets: dict[str, list[float]], market: str = "BTC/USDT:USDT") -> dict:
    out: dict = {"vs_btc": {}, "pairwise": None}
    for p in TRADFI_PAIRS:
        if p in rets and market in rets:
            out["vs_btc"][p] = _corr(rets[p], rets[market])
    a, b = TRADFI_PAIRS[0], TRADFI_PAIRS[1]
    if a in rets and b in rets:
        out["pairwise"] = _corr(rets[a], rets[b])
    return out


# ---------------------------------------------------------------------------- manager state
K_STATE = "tradfi"


LISTED_MIN_S = 600  # a pair must have been on our pairlist this long before its absence from the whitelist counts


def refresh(reg, ft, pairs: list[str], enabled: bool, now: datetime | None = None,
            listed: list[str] | None = None) -> dict:
    """Lane state for the manifest and the control room (every 15 min, observation + sizing):
    availability on the account, sessions, correlations with BTC from the bot's own candles.

    `listed` = the pairs on the pairlist file the bot reads. A pair missing from the bot's
    whitelist counts as unavailable only after it has been listed for 10 minutes (the bot reloads
    the pairlist every 5): right after a restart the lane's pairs are not listed yet."""
    from aitrader import observe
    now = now or datetime.now(UTC)
    old = reg.kv_get(K_STATE) or {}
    try:
        wl = (ft.whitelist() or {}).get("whitelist") if ft is not None else None
    except Exception as e:  # noqa: BLE001 – the bot may be restarting
        log.info("tradfi: whitelist unavailable: %s", e)
        wl = None
    avail = availability(pairs, wl)
    since = dict(old.get("listed_since") or {})
    if listed is not None:
        on = set(listed)
        since = {p: since.get(p) or now.timestamp() for p in pairs if p in on}
        for p in pairs:
            if avail.get(p) is False and now.timestamp() - float(since.get(p) or now.timestamp()) < LISTED_MIN_S:
                avail[p] = None  # not on the pairlist long enough (or at all): no answer yet
    prev, miss = old.get("available") or {}, dict(old.get("miss") or {})
    for p, v in list(avail.items()):
        if v is None:  # the bot did not answer: keep the last known answer
            if p in prev:
                avail[p] = prev[p]
        elif v:
            miss.pop(p, None)
        elif prev.get(p) is True:
            # a tradable instrument is dropped only on the second missing reading in a row (a
            # pairlist reload or a short exchange maintenance must not switch the lane off)
            miss[p] = int(miss.get(p, 0)) + 1
            if miss[p] < 2:
                avail[p] = True
            else:
                miss.pop(p, None)
    corr = old.get("corr") or {}
    try:
        live = [p for p in pairs if avail.get(p)]
        if live and ft is not None:
            corr = correlations(observe.hourly_returns(ft, live + ["BTC/USDT:USDT"]))
    except Exception as e:  # noqa: BLE001
        log.info("tradfi: correlation unavailable: %s", e)
    state = {
        "ts": now.isoformat().replace("+00:00", "Z"), "enabled": bool(enabled), "pairs": list(pairs),
        "available": avail, "miss": miss, "listed_since": since, "probe_since": old.get("probe_since") or now.isoformat().replace("+00:00", "Z"),
        "open_now": {p: is_open_now(p, now) for p in pairs},
        "corr": corr, "scale": {p: corr_scale((corr.get("vs_btc") or {}).get(p)) for p in pairs},
        "calendar_until": CALENDAR_UNTIL.isoformat(),
    }
    changed = {p: v for p, v in avail.items() if v is not None and (old.get("available") or {}).get(p) != v}
    reg.kv_set(K_STATE, state)
    if changed:
        txt = ", ".join(f"{INSTRUMENTS[p]['symbol']} {'доступен' if v else 'НЕ доступен'}" for p, v in changed.items())
        reg.event("tradfi", f"TradFi на демо-счёте: {txt}", "info" if all(changed.values()) else "warning",
                  data={"available": avail})
    return state


PROBE_MINUTES = 45  # daily re-probe window from 00:00 UTC: listed ≥ 10 min, ≥ 2 refreshes inside it


def usable_pairs(state: dict | None, pairs: list[str], now: datetime | None = None) -> list[str]:
    """Pairs the lane may put on the manifest: everything not confirmed unavailable. An
    instrument the bot has dropped from its whitelist goes back on the pairlist for 45 minutes
    after 00:00 UTC every day (Bybit may list it later, e.g. on the demo account); the 15-minute
    `refresh` reads the answer inside that window."""
    av = (state or {}).get("available") or {}
    now = now or datetime.now(UTC)
    probe = now.hour == 0 and now.minute < PROBE_MINUTES
    return [p for p in pairs if av.get(p) is not False or probe]


def breaker_state(closed: list[dict], attempts: list[float], now: float, *, max_emergency: int = 2,
                  max_attempts: int = 3, window_s: float = 24 * 3600) -> str | None:
    """Circuit breaker for one TradFi pair (pure; ftbase feeds it). Bybit may refuse a TradFi
    order or its exchange stop on a given account (product agreement, size or margin-mode rules);
    Freqtrade then logs a warning or closes the position at once ("emergency exit"). Without a
    breaker the next signal would repeat that every candle. Returns a reason to pause new entries
    on the pair for 24 h, or None:
      * ≥ `max_emergency` emergency exits in the last 24 h;
      * ≥ `max_attempts` entry attempts in the last `window_s` without any trade appearing."""
    day = now - 86400
    em = sum(1 for t in closed if (t.get("exit_reason") or "") == "emergency_exit" and (t.get("close_ts") or 0) >= day)
    if em >= max_emergency:
        return f"{em} emergency exits in 24 h (exchange refused the stop or the order)"
    recent = [a for a in attempts if a >= now - window_s]
    if len(recent) >= max_attempts:
        return f"{len(recent)} entry attempts in {window_s / 3600:.0f} h without a filled trade"
    return None
