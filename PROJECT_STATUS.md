# PROJECT_STATUS

_Last updated: 2026-11-21 17:10 CET_

## Summary
The system is **deployed and running autonomously on Bybit Demo**. It never trades real money: `demo_trading` is hard-required.

Architecture, split by load:
- **Railway** (one container, volume `/data`, EU West): only trades, learns from fills, manages the strategy lifecycle and serves the web HQ. **No heavy compute.**
- **GitHub Actions research lab** (`research-lab` workflow, public repo, 4 vCPU runners, free minutes): all hyperopt, walk-forward, stress, robustness and Monte Carlo. It sends only compact results to the server.

Links and rules:
- Web: https://aitrader-production-cf456409.up.railway.app (basic auth: user and password in the Railway variables `WEB_USER` / `WEB_PASSWORD`, set by the owner on 2026-11-21). `/` = **control room** (primary screen), `/hq` = 3D office, `/terminal` = classic terminal.
- Repo: `mailzastraze-ctrl/bybit-ai-trader` (**public** since 2026-11-20; no secrets in the repo or its history). Railway deploys on code changes only (`src`, `ft`, `config`, `Dockerfile`, `pyproject.toml`); research commits do not redeploy.
- No profitability is claimed. Every number comes from real demo fills or from walk-forward out-of-sample backtests.

## Original brief vs. implementation
| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Monitor markets, find opportunities | ✅ | Lab scans **Bybit** USDT perps (via the EU relay; OKX fallback) with VolumePairList and scores trend vs. mean-reversion per pair. The server receives the universe and the scores |
| 2 | Research, **develop**, test, optimise multiple strategies | ✅ | **6 families**: EMA trend, Bollinger mean reversion, Donchian, squeeze, **time-series momentum (vol-scaled)** and **funding-rate crowding reversal**, plus structural genes. A UCB bandit, learnings (A/B) and refinements of promising strategies choose the next experiment |
| 3 | Entries, SL, TP, sizing and exits optimised together | ✅ | ATR stop, R-multiple TP, trailing, time exit and conviction-weighted risk sizing in one parameter vector |
| 4 | Realistic validation, costs, OOS, overfitting control | ✅ | Walk-forward OOS, fees + slippage + funding, 2× cost stress, ±10% parameter perturbation, Monte Carlo and WFE gates. **Deflated Sharpe counts every trial of the last 90 days** (`research/ledger.json`), so continuous searching cannot inflate significance |
| 5 | Execute and manage trades on Bybit Demo, controlled experiments | ✅ verified | Execution test passed: entry → **exchange stop-loss** → exit. Exploration sleeves trade at 0.1% risk |
| 6 | Analyse, learn, promote only after independent validation | ✅ code / ⏳ trades | Learner (pair exclusion, MFE, time exits, side asymmetry, gate failures) with A/B pruning. Lifecycle: exploration → incubation → forward demo evidence → production. Revalidation every 14 days runs in the lab; a failed one retires the strategy |
| 7 | Web terminal | ✅ live | **Control room** (primary, desktop + phone): capital curve, positions with protection state, forward-test verdict, 4 live lab runners, results with fold squares, bandit, gates, lifecycle, goals, readiness, log, learnings, closed trades. **3D HQ v3** at `/hq`: real data on every screen (live 1h candles with entry/stop/target, live GitHub hyperopt epochs, fold results, gates, bandit, market map, goals). Company mission board, stand-up meetings built from real numbers, GitHub-lab cloud with data beam, expressive characters. Rendered headlessly on every UI change (`hq-preview` workflow, screenshots in `docs/preview/`, fails on JS errors) |
| — | Cloud, independent of your PC | ✅ / ⚠️ | Railway **trial** credit runs out in about 15 days. Hobby is needed for indefinite operation |
| — | GitHub + PROJECT_STATUS | ✅ | CI green with the real Freqtrade image; 113 tests |

## Engine ↔ bot parity (2026-11-21, owner's request: "полностью и чётко")
**Problem found:** of the first 32 autopilot strategies tested in freqtrade, 24 collapsed (PF 0.15–0.86) on the coins where the engine showed PF ≥ 1.4. The signals were fine; the exits were not the engine's.
- Example: an engine "trail 3×ATR from entry" became our ratchet with `trail_rr` 0.5, which jumps the stop to the entry price at +0.5 R.
- An engine "no exit rule" became trailing after 3 R plus break-even at 2 R.

**Fix:**
- New exit mode `exit_mode = 1` ("Strategy Lab exits") in `riskcore.managed_stop`, used by every screener/autopilot configuration (`screen.to_params`): ATR stop, optional R take profit (`lab_tp`, 0 = none), optional chandelier trail from the entry on the current ATR (`lab_trail`). No break-even, no ratchet. It is the same in backtests and live.
- It is never part of the generated search: `LAB_EXIT` is pinned to 0, and refinements keep it.
- The z-score twin now uses the population σ, as the engine does.
- **Bar-for-bar parity test:** `screener/parity.js` + `tests/test_screen.py::test_twin_signals_match_the_owner_engine_bar_for_bar` cover all 10 engine rules (13 cases). Entries and exits are identical on every bar after warm-up.
- **Exit-mode test:** `test_strategy_lab_exits_match_the_engine`.
- Survivor ids are versioned (`x2`), so every configuration tested with the old approximation gets a fresh walk-forward with the exact exits.
- **Remaining, deliberate difference:** a take profit fills at the touch candle's close in freqtrade backtests, while the engine fills it at the level. This is conservative and close to live behaviour: live waits at the level for 90 s, then crosses.

## Position management like a careful trader (2026-11-21, owner's request)
**Live protection (protective direction only):**
- **Take-profit execution:**
  - Before: when price touched the target, the passive maker order followed the price for up to 90 s and could fill below the target after a wick.
  - Now: the order waits at the target, then crosses as before.
- **Risk per side:** at most 4% of equity at stops in one direction (`max_side_risk`, half of the 8% total). Crypto positions in one direction are close to a single bet; at the time of this change all 7 open positions were shorts.
- **Market-shock guard:** if BTC moves ≥ 2.5% in one hour against a side, every position of that side that is ≥ 0.5 R in profit gets its stop moved to break-even (+ fees). Nothing is opened or closed by this rule, and losing positions keep their stop.

**Careful-trader exits as researched genes** (off by default; searched in ~35% of new experiments, refinements keep them):
- `tp_near` / `tp_lock`: once `tp_near` of the way to the take profit has been reached, lock `tp_lock` of the best open profit (the habit of not giving back a nearly-won trade).
- `event_lock`: 2 h or 8 h before a US CPI, jobs or Fed release, lock half the profit if ≥ 0.5 R.
- `vol_shock`: trail from the best price once current ATR ≥ 1.6× / 2× / 2.5× the entry ATR.

All three live in `riskcore.managed_stop`, with identical inputs in backtests and live. The walk-forward, the decoys and the forward test decide whether "closing a bit early" earns more than it gives up.

## Market context + simpler control panel (2026-11-21, owner's request)
**Context as testable conditions (research decides, nothing is traded on faith):**
- New structural genes for every family, tested like `htf_trend` / `vol_regime`:
  - `session`: Asia, Europe, US or Europe+US exchange hours. Local hours with DST via zoneinfo: Tokyo, Hong Kong, Frankfurt, London, New York.
  - `no_weekend`.
  - `event_guard`: no entries ±2 h or ±12 h around US CPI, jobs report (NFP) and Fed decisions.
- **Calendar:** official dates in `src/aitrader/data/macro_events.json`, 2022–2027, from federalreserve.gov and bls.gov with the release times.
- The genes only remove entries, and they behave identically in backtests and live (decision time = candle close).
- They are searched in about 35% of new experiments and pinned off elsewhere, so the usual search keeps its speed. Refinements keep a candidate's genes.

**Live snapshot ("Мир сейчас"):**
- Sources:
  - Fear & Greed (alternative.me);
  - Deribit BTC DVOL with its 30-day percentile;
  - Bybit long/short account ratio for BTC, ETH and SOL;
  - Bybit delisting announcements.
- Refreshed every 15 min by the manager, with 6-second timeouts. Failures keep the last value and never block trading.
- An hourly history is kept for 90 days as evidence for later research. A long/short "crowd" gene comes once that history exists.
- **Safety rule:** a coin Bybit announces to delist gets no new entries; open trades keep their exits.

**Control panel (owner's convenience):**
- **Top summary** in plain Russian (bot, research, "can it make money") plus **"Требует внимания"**. It lists only things that need the owner, or says that nothing does.
- **Five key tiles:** capital, demo result, in the market now, can it make money (forward test), real-money readiness.
- **"Мир сейчас" panel** next to the equity chart:
  - which exchanges are open, with countdowns;
  - next US macro releases in the owner's local time;
  - fear/greed, options nervousness and the crowd on Bybit.
- **Layout:** open positions full width; the pipeline with the forward-test detail folded; goals and the log.
- **Header:** compact, the "updated" chip is gone.
- **Phone:** tiles in two columns, the pipeline in two columns, the strategy id hidden.
- **Other tabs:** goal units in Russian, lab chip grammar fixed.

## Strategy Lab autopilot (2026-11-21, owner's request)
The owner's goal: the company should find what his Strategy Lab found by hand (stable strategies with rare, accurate trades over 3 years plus the last 3 months, e.g. EMA cross on BTC 6h), automatically and without the Lab's many tabs, and trade the best ones on at least 15 coins.

**Autopilot** = `screener/screen.js --mode swing`, running in the lab's `screen` job next to the pooled 15m/1h mode:
- **Data:** top 15 coins by volume, 2h / 4h / 6h / 12h, about 3.3 years.
- **Search:** the owner's `engine.js` (10 rules × random parameters × exits) on everything except the last 90 days.
- **Seven automatic checks.** The Lab's tabs became filters, and failures are never shown:
  1. Stability: 0.5–12 trades/month and at least 20 trades, PF ≥ 1.4, every third of the period profitable, R² ≥ 0.75, max DD ≤ 25%.
  2. Robustness: at least 70% of neighbouring parameter sets are profitable.
  3. Walk-forward: the same search, re-run without the last year, must pick a configuration that is profitable on that year.
  4. Last 3 months: unseen by every search, at least one trade and not losing.
  5. Monte Carlo: 95th-percentile drawdown ≤ 35% and P(loss) ≤ 10%.
  6. Other coins: the coins where the configuration also holds join its trading list, up to all 15.
  7. Not luck: see the decoy control below.
- **Decoy control (why the seven checks alone are not enough).** We ran the same search on pure random walks. It "found" 42–62 configurations that passed all seven checks, with Sharpe above 2, PF up to 4.5 and several coins each. That is the multiple-testing effect behind the many "working" strategies seen when searching by hand.
  - The search therefore also runs on decoys: the same coins with daily return blocks shuffled in time. One permutation is shared by all coins, so correlations survive and real predictability is destroyed.
  - A survivor is accepted only above the score at which decoys would make up at most 20% of the accepted list (target–decoy false-discovery control).
  - Tests: random walks → 0 accepted; a planted shared trend → accepted with all checks passing.
- **Downstream (nothing weakened):**
  - Accepted strategies go first to the freqtrade walk-forward with real fees and funding (tested on up to 15 coins), then to the gates and verdict.
  - Exploratory and validated strategies trade on demo across every coin they passed on, then go through the forward test. Production still requires forward evidence.
  - Autopilot strategies take the demo lane first. They replace ordinary near-miss exploration sleeves that have no live edge.
  - `max_pairs_per_sleeve` was raised from 8 to 15. Strategies already tested in the last 21 days are not re-tested.
- **Bot:** sleeves on 2h–12h run on the 15m bot via informative pairs (signal on the first 15m candle after the higher candle closes, no look-ahead). Backtest and forward-test warm-up scales with the timeframe (720 candles).
- **UI:** the "Стратегии" tab shows an autopilot summary (variants tried, how many passed all seven checks, how many decoys pass, how many accepted, coins covered). Cards show the 3-year record and trades per month. The drawer has a chart with the unseen periods shaded and all seven checks with their values. Rejected strategies are counted, not shown.
- **Honest expectation:** if the market offers fewer real edges than hand searching suggested, the autopilot accepts few or none and says so. It does not force 15 coins with lucky strategies.

## Overnight review and fixes (2026-11-21 morning)
**Research lab:** 4 runs completed overnight, ~113 walk-forward experiments.
- Candidates: 7 exploratory, 0 validated.
- The edge that keeps appearing is **time-series momentum (`tsmom`, 1h, long lookback)**: 5 candidates with PF 1.13–1.72 out-of-sample.
- Most other families lose out-of-sample after costs (PF 0.5–0.95).

**Screener:** 3 runs × ~250 000 combinations. 47–73 per-coin configurations looked profitable on the unseen 40%, but **0 survived the false-discovery correction**. They are indistinguishable from luck, which explains why single-coin analyzers find "many profitable configurations". The screener now runs in **pooled mode**: one configuration across all coins of a timeframe, which gives hundreds of holdout trades per test.

**Forward test:** the book has 118 frozen strategies, but only 1 completed forward trade so far. Most strategies were frozen within the last hours and their trades are still open; a diagnostics line was added.

**Live:** 16 exploration strategies trading on demo; 2 closed strategy trades so far.

**Bugs fixed:**
1. Bybit demo's order-book websocket failed with "already subscribed" every 5 s, so maker entries could not cross and timed out after 12 min. Pricing now uses the ticker, with fallbacks; no errors after redeploy.
2. A zero-trade experiment broke the Deflated Sharpe trial count for every later experiment of its runner (10 of 30 failed in one run).
3. Open interest was re-downloaded for 760 days in every oi_flow experiment; it is now downloaded once per run and cached.
4. Timeframe is now shown in lab logs and reports.

**3D office:** maintained by the owner via ChatGPT since 2026-11-20 (`hq*.js`, `hq.html`, assets); not changed here.

## Weak spots fixed (2026-11-20, 22:50)
- **Screener false-discovery control:** every holdout test gets a p-value. Survivors must pass Benjamini–Hochberg (q = 0.2) across all holdout tests of the run, and the run reports the expected number of lucky survivors.
- **New information sources** (beyond price and volume):
  - `rel_strength`: a coin's performance relative to BTC (cross-sectional momentum). BTC candles are merged on the same candle.
  - `oi_flow`: price move combined with the **open-interest** change, in two modes (confirm a breakout carried by new positions, or fade a move on collapsing OI). Research downloads Bybit OI history (`/v5/market/open-interest`, incremental, through the relay); the live bot fetches recent OI via ccxt; OI is merged as of the candle start.
  - 18 families in total.
- **One web interface in Russian:** tabs Обзор / Стратегии / Лаборатория / Сделки / 3D-офис. Strategy cards are in the style of the owner's Strategy Lab. The old `/terminal` redirects to the control room, and the company log is translated.

## Owner's Strategy Lab integrated + owner's rules (2026-11-20, 22:00)
Research pipeline, end to end:
1. **Stage 1, mass screener** (`screener/`, Node): the owner's Bybit Strategy Lab engine (`engine.js`, unchanged) tries thousands of strategy × parameter × exit combinations per coin and timeframe (15m + 1h, 1x, Bybit fees + slippage).
   - It searches on the first 60% of the history.
   - Survivors must stay profitable on the **unseen last 40%** with a steady equity curve (R² ≥ 0.5), a positive last 3 months, ≥ 15 trades, max drawdown < 30% and PF ≥ 1.15.
2. **Stage 2, freqtrade walk-forward:** survivors run first on the 4 runners as fixed configurations: 4 unseen 90-day windows, double costs, Deflated Sharpe and steadiness.
3. **Stage 3, forward test** on live Bybit data after freeze.
4. **Stage 4, demo trading** at 0.1% risk, then readiness.

Strategy families:
- **18 families.** All 10 engine strategies have exact twins: SuperTrend, MACD, ADX+DI, Hull MA, RSI, Stochastic, Z-score, EMA cross, plain Bollinger, turtle. The 6 earlier families remain.
- The owner's own SOL 15m z-score configuration is imported (`research/external/`). It is walk-forward tested with fixed parameters and forward-tested.

Ranking and the trading bot:
- **Equity steadiness** (owner's criterion), measured on unseen windows: curve R², share of profitable months, last 3 months. It is part of the ranking score and shown in the UI.
- **One bot, two timeframes:** the demo bot runs on 15m candles. 1h strategies are computed on hourly candles and fire on the first 15m candle after the hourly close (no look-ahead). No second process is needed.

Owner's rules:
- **No leverage** (hard 1x cap in code).
- **Maker-first entries and exits**: 0.02% instead of 0.055%. Stop-type exits cross immediately.
- **Learning limits relaxed for demo:** up to 24 exploration strategies, 6 per family, 4 per coin, 45 coins, 40 open trades. Each trade risks 0.1%, and open risk is capped at 8%.

Server footprint:
- Measured: freqtrade ≈ 430 MB, web+manager ≈ 180 MB, CPU ≈ 0.03–0.06 vCPU. Estimated cost ≈ $7–9/month on Hobby; `MALLOC_ARENA_MAX=2` is set.
- The owner paid for Hobby on 2026-11-20. Set a usage limit (e.g. $20).

## Forward test — "can this system make money?" (2026-11-20, 21:00)
The direct answer to the owner's question, in days to weeks instead of months.
- **Shadow book** (`forward.py`, `research/shadow.py`): every finished walk-forward experiment is **frozen** when it finishes (parameters and pairs never change afterwards). Each lab run backtests every frozen strategy (up to 120, last 60 days) on real Bybit candles **after its freeze time only**, with fees and the 5 bp/side slippage haircut. Open trades at the data end are excluded.
- It includes the weak candidates on purpose: the test is whether the research's own ranking predicts unseen performance.
- **Pre-registered verdict** (fixed before any forward data existed): the top quartile by backtest score at freeze vs the rest.
  - too early: < 100 forward trades or < 7 days;
  - early read: direction only;
  - **works**: ≥ 200 trades, ≥ 14 days, PF ≥ 1.15 after costs, daily-pooled t ≥ 2.0;
  - **not working**: PF < 1.0 or return ≤ 0 at that point. That would mean the search finds noise and needs new data sources (OI, liquidations, cross-sectional), not more of the same.
- **Immediate history indicator:** does a profitable first half of the walk-forward holdout predict a profitable second half?
- **Forward-proven strategies** (≥ 20 forward trades, PF ≥ 1.3 after costs, positive) become `exploratory` (`fw-…`) and can get demo capital.
- Shown at the top of the control room, as a company goal and at `/api/forward`.

## Research throughput ×4 (2026-11-20, 21:00)
`research-lab` is now `prep` → **4 parallel runners** (4 vCPU each) + `shadow` (forward test) → `merge`.
- Each runner opens with a different family (UCB rank), and its local bandit counts the run's own finished experiments.
- Deflated Sharpe is computed over every trial: the 90-day ledger plus all four runners.
- Private-repo fallback: 1 runner.

## Honest numbers (2026-11-20, 21:00)
- PF no longer shows a fake 99 without losses; the PF goal needs ≥ 30 trades.
- Infrastructure losses (cancelled runner, restart) count as `lost`, not research failures.
- Capital = the bot's USDT trading capital (≈ 49.8k). The self-test also shows the whole demo account value including other coins (≈ 168k).

## Success-critical upgrades (2026-11-20, evening)
- **Real-money readiness gate** (`readiness.py`, `/api/readiness`, HQ mission panel). It is advisory and never switches by itself. All 8 checks are evaluated on post-promotion production trades:
  - ≥ 90 days of forward trading;
  - ≥ 250 trades;
  - ≥ 2 strategies with daily correlation < 0.5;
  - t ≥ 2.5;
  - PF ≥ 1.3;
  - drawdown ≤ 10%;
  - profitable in 2 of 3 time thirds;
  - no divergence from out-of-sample results.
- **Demo → reality haircut:** 5 bp of slippage per fill on every demo trade (the demo never touches the real book). Promotion, retirement and goals all use the realistic P&L.
- **Active position management:** the stop is checked every ~5 s and mirrored to the exchange.
  - It moves to break-even (+ fee buffer) at `be_rr`·R.
  - From `lock_rr`·R a profit ratchet locks `lock_frac` of the best open profit, then the ATR trail takes over.
  - The three thresholds are optimised exit parameters.
  - Verified live 15:15–15:18 UTC: DOGE short #3 (entry 0.05648), stop moved to break-even at 0.05641, then ratcheted to 0.05566 (≈ +28 USDT locked).
- **Portfolio limits:** open risk at stops ≤ 3% of equity, ≤ 7 positions per direction, ≤ 2 sleeves per family, volatility targeting (daily equity vol > 1.5% scales risk down), correlated sleeves (corr > 0.7) at half risk, exploration lane 5.
- **Maker-first entries:** limit orders at the touch, crossing the spread after 3 min (maker 0.02% vs taker 0.055%).
- **Stricter validation:** 365-day training, a full year of out-of-sample data as 4 unseen 90-day slices, a new fold-consistency gate (≥ 3/4 slices profitable), ≥ 760 days of history, a 40-pair research universe.
- **Registry backup** every lab run (30-day artifact; the repo is public, so the demo data in it is visible to GitHub users).
- **Not done yet:**
  - Telegram alerts (need a bot token from the owner);
  - cross-sectional momentum / open-interest data;
  - a real-account switch procedure.

## Real Bybit research data (2026-11-20)
Bybit blocks US IPs, and GitHub runners are in the US. Probe result: a direct request from the runner gets HTTP 403, while the same request through the server relay gets HTTP 200.

How the data reaches the lab:
- The live server (Railway EU) relays **GET-only `/v5/market/*`** requests to `api.bybit.com` at `/relay/`. Tokens are 8-hour HMACs issued via OIDC; no new ports and no API keys are involved.
- Research freqtrade subprocesses load a `sitecustomize` hook that rewrites ccxt's Bybit URLs to the relay. ccxt's own proxy options conflicted.

First live run 15:44 UTC: instruments, risk limits, 1h klines and funding history were all downloaded through the relay with HTTP 200. Fallback to OKX applies if Bybit is unreachable, and no experiments run on a universe smaller than 4 pairs.

Incident: the first attempt (ccxt proxy conflict) produced 50 empty experiments. The guard above was added and that batch file removed.

## HQ staff (2026-11-20)
- **Model and motion:** motion-captured skinned characters (three.js Xbot, Mixamo rig) with idle/walk mocap plus additive nod, head-shake and slump.
- **Procedural poses** (world-axis, rig-independent): sitting, typing, talking, phone, coffee, cheering, clapping, pointing, whiteboard.
- **Clothing shader:** skin, hair, shirts/jackets by department, lab coats, ties, belts, trousers, shoes.
- **Fallback:** the procedural rig if the model can't load.

## Research lab (GitHub Actions), added 2026-11-20
1. `GET /api/lab/state` fetches learnings, revalidations due, strategies worth refining and the family bandit stats.
2. Budgeted cycle of 170 min on public repos: revalidations → ~25% refinements → UCB new searches. Live progress (stage, epoch, best in-sample) is posted to `/api/lab/progress`.
3. Merge with the 90-day ledger DSR → `POST /api/lab/import`. Results are committed to `research/imports`, `research/reports` and `research/ledger.json`.
4. The next run is chained immediately (public repo). Cron restarts serve as a watchdog.

Auth is GitHub OIDC: the server accepts only tokens of this repository's `main` branch, with no stored secret. `lab-probe` verifies this end to end (HTTP 200 on 2026-11-20).

First run, 2026-11-20: scan finished at 14:56 UTC, experiments streaming.

## Verified in production
- Self-test 6/6 (demo endpoint, auth, futures, whitelist, `Demo trading enabled for Bybit (Demo)`).
- Execution test: XRP entry 0.9543 → exchange stop 0.9315 → exit 0.9542 (−0.08 USDT fees/spread).
- First autonomous strategy trade: 13:00 UTC, DOGE long, stop on the exchange.
- Bulk batch b20261120-44725886469 (29 OOS experiments, OKX 1h): **0 validated**, 7 exploratory after a stricter re-filter.
  - Breakout and squeeze **lose OOS after costs**.
  - EMA trend and mean reversion show OOS edge but fail Deflated Sharpe, so they run as tiny-risk exploration.
- Server since the remote-research switch: research process off, no OOM. Supervisor log line: `research mode: remote`.

## Honest outlook (owner asked)
- A subjective estimate of ~35–50% chance to find a modest, robust edge, most likely trend/time-series momentum.
- Large stable returns are unlikely.
- Demo fills are kinder than live trading.
- Next levers:
  - maker/limit entries (cost);
  - funding/basis data (added);
  - 4h/1d momentum horizons (TSMOM added);
  - a portfolio of weak, uncorrelated edges;
  - time for forward evidence.

## Bugs found by real runs (all fixed, with regression tests)
userdir must exist · absolute `file:////` pairlist URL · OOM on 1 GB (now: no research on the server) · universe too small · artifact permissions · forced-entry stake · keep-alive reset · hyperopt hang (watchdog) · weak candidates (stricter gates + retraction) · placeholders blocking research · CI missing psutil.

## Needs the owner
1. A usage limit in Railway (Hobby is paid since 2026-11-20).
2. Optional: more configurations from the owner's Strategy Lab can be dropped into `research/external/*.json`; the screener already runs the same engine automatically.
3. A second Railway project `boreal-quant-demo` (empty repo) appeared at 20:29 CET, not created by this system. It spends the same trial credit; delete it if unused.

Owner decisions (2026-11-20): keep the current Bybit **Demo** API key (no rotation); make the repo public for free research compute.

## Known limitations
- Research data now comes from Bybit through the server relay. If the relay is down, a run falls back to OKX data and says so in its report.
- Backtest TP fills at candle close, not intrabar.
- Funding family: live funding candles are requested only when a funding sleeve is deployed. If data is missing, the family stays silent.
