# TradFi lane — gold and the S&P 500 on Bybit Demo

_23.11.2026, owner's request (a ChatGPT recommendation, reviewed by Claude). Branch `tradfi-gold-spy`,
not deployed. Code: `src/aitrader/tradfi.py`, `src/aitrader/families/tradfi.py`, configurations
`research/tradfi/*.json`, tests `tests/test_tradfi.py`._

## 1. What the recommendation got wrong, and what was changed
| Recommendation | Fact (checked 23.11.2026) | Done |
|---|---|---|
| S&P 500 = `SPXUSDT` | On Bybit `SPXUSDT` is **SPX6900, a memecoin**. The S&P 500 trades as the SPDR S&P 500 ETF perpetual `SPYUSDT` (Bybit TradFi perpetuals, listed May 2026). | `SPY/USDT:USDT`; `SPX/USDT:USDT` is explicitly not TradFi (`NOT_TRADFI`) and stays a crypto coin. |
| Gold = `XAUUSDT` | Correct: gold perpetual, listed in spring 2026. | `XAU/USDT:USDT`. |
| Walk-forward, OOS, robustness on these instruments | The system's walk-forward needs ≥ 120 days of indicator warm-up + training + test quarters (min. 760 days of history for research pairs). Gold has ~8 months on Bybit, SPY ~6. A walk-forward today would test nothing. | Fixed, pre-registered rules (nothing to train); evidence = demo trades and, opt-in, the forward book (§4). |
| Trade them like crypto | The underlying markets close (NYSE 6.5 h a day, gold 23 h × 5 days); the perpetuals trade 24/7 on a stale index outside the session. | Entries only while the underlying is open (§3). |

Availability on the demo account could not be checked from the development sandbox (Bybit is not
reachable from it). The live bot checks it itself (§5).

## 2. Strategies (pre-registered 23.11.2026, nothing optimised)
All on 4h candles, exploration risk (0.1 % of equity per trade × correlation scale), 1x, exchange stop.

| id | Strategy | Instruments | Rule |
|---|---|---|---|
| `tf-trend-4h-30d` | Trend Following | gold, S&P 500 | Exactly the crypto benchmark (`tsmom`): 30-day return in 30-day volatility units, entry ±0.5, exit when momentum turns, 4×ATR stop. |
| `tf-gold-regime-4h` | Gold Regime | gold | Bull/bear regime of the ≈50-day trend; buys the end of pullbacks (sells rallies), no entries in volatility shocks (ATR% > 1.5× its 60-day median), exit when the ≈10-day trend crosses back; 3×ATR stop + chandelier trail 4× current ATR. |
| `tf-rotation-4h-60d` | Momentum Rotation | gold ↔ S&P 500 | Dual momentum: holds whichever has the stronger risk-adjusted 60-day momentum if it is positive (band 0.25 σ), long only; 4×ATR stop. |

The two new families are **not** in `FAMILIES`: the lab's bandit, generator, screener and explorers
are unchanged; `get_family` resolves them for the bot and for backtests.

## 2a. Gold on demo: the autopilot's best (owner, 23.11.2026)
The owner asked for XAUUSDT on demo with **the best strategy found by stability + return**. Bybit's
XAUUSDT is too short for the Strategy Lab autopilot (≥ 900 days), so it ran on PAXG (tokenized gold,
24/7) 2023-07 → 2026-11: branch workflow `tradfi-gold-screen` (`.github/tradfi/gold_candles.py`,
`screener/screen.js --mode swing`, 10 rules × parameters × exits on 2h/4h/6h/12h, 10 decoy copies).
663 329 backtests; 62 configurations passed all seven checks; decoys passed 8.4 per copy; 23 also
significant on unseen data (BH q = 0.2). Results: `research/tradfi/screen/`.

Chosen rule: the highest score (Sharpe × equity R² × robustness) among those also significant on
unseen data → **`xau-macd-12h`**: MACD 11/56/10 with the zero-line filter on 12h, stop 1.5×ATR, target
4R, chandelier trail 3×ATR (engine exits, `exit_mode` 1). Search years (2.7 y): 44 trades, PF 3.31,
DD 6.3 %, R² 0.92; walk-forward year: 20 trades, PF 1.97; last 90 days: 5 trades, PF 8.8; all
neighbouring parameter sets profitable; Monte Carlo DD95 10.5 %. (Engine figures at 100 % of capital;
the bot risks 0.1 % per trade.) Caveats: PAXG proxy, a gold bull market, best of many – the forward
record decides. On demo gold trades **only** with this strategy (`demo_pairs`); the three
pre-registered strategies keep gold in their hypotheses, and Trend Following and Rotation trade SPY.

## 3. Execution and risk
- One bot, one manifest: the lane's sleeves are added next to crypto and the core, outside the crypto
  slots and whitelist cap. A crypto strategy can never trade gold or SPY (filtered in the manifest and
  in the research universe).
- **Sessions** (`tradfi.session_open`): NYSE regular hours incl. 2025–2027 holidays and early
  closes, DST-aware; gold Sunday 18:00 → Friday 17:00 New York with the daily 17:00 break. A signal
  raised while closed is carried to the first open decision unless the strategy's own exit is on by
  then. Exits and the exchange stop work 24/7. The calendar ends 2027-12-31: extend it in December 2027.
- **Limits** — all existing ones apply unchanged (8 % open risk, 4 % per side, exploration caps,
  kill-switch, demo-only, 1x); the lane adds only stricter ones: ≤ 2 TradFi positions,
  ≤ 0.5 % of equity at their stops, entries only with the market open.
- **Correlation**: every 15 min the manager measures each instrument's correlation with BTC on the
  bot's hourly candles; risk × 1/(1+ρ⁺) (floor 0.5, never above 1). The open book's effective number of
  independent bets (`observe.exposure`) includes the lane.
- **Circuit breaker**: if Bybit refuses a TradFi order or its exchange stop (Freqtrade then logs or
  closes at once, "emergency exit"), entries on that pair pause for 24 h after 2 emergency exits in
  24 h or 3 entry attempts in 24 h without a fill.
- **Recovery**: a TradFi trade keeps its own plan (Freqtrade custom data) across restarts; with the
  lane switched off or the instrument gone it stays in the manifest as `closing` and exits by its
  own rules.

## 4. Evidence
- Demo trades: synced like every trade (`live_trades`, tag = config id).
- Forward book (opt-in, `TRADFI_FORWARD_BOOK=1`): the three configurations as hypothesis **TF1**
  (shadow only, frozen at first registration, line `hypothesis:TF1`, never promoted, outside the
  research verdict). Off by default: under DECISIONS §3 one failed forward test marks the whole v3
  recording `partial` (red flag), and the lab's Bybit candles for these contracts are unproven. The lab
  downloads TradFi candles in a separate call, so they can never cost the benchmark or H1 their data.
- Honest scale: 2 instruments, multi-week holds → ~10–40 trades a year for the whole lane. A
  statistical verdict takes years; judge against buy & hold of the same instrument, not BTC.
- Walk-forward on Bybit candles becomes possible at the earliest ≈ 300 days after listing (one test
  quarter: early 2027 for gold, spring 2027 for SPY), with the full 4 quarters ≈ 570 days (late 2027).

## 5. Switches and checks after a deploy
- `TRADFI_ENABLED=0` switches the lane off (open TradFi trades are still managed to their exit).
- `HEALTH` line: `tradfi=[XAU ok open, SPY n/a]` (ok = on the bot's whitelist, n/a = Bybit does
  not list it for the account, ? = not known yet). Events `TradFi на демо-счёте: …`.
- The manager runs the TradFi execution test (entry → fill → exchange stop → exit, 60 USDT,
  only with the market open) once the lane is confirmed; result in kv `tradfi_exec_test` and an event.
- An unavailable instrument goes back on the pairlist 00:00–00:45 UTC every day (re-probe).
