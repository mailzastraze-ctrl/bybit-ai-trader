# CHANGELOG

History of the system, newest first. `PROJECT_STATUS.md` holds only the current state.

## 2026-11-23 (branch `tradfi-gold-spy`, not deployed) — TradFi lane: gold and the S&P 500 on Bybit Demo
Owner's request (a ChatGPT recommendation, reviewed). Instruments: `XAU/USDT:USDT` (gold) and `SPY/USDT:USDT` (S&P 500 via the SPDR ETF perpetual) – **not** `SPXUSDT`, which on Bybit is the SPX6900 memecoin. Three pre-registered strategies on 4h candles, nothing optimised: Trend Following (`tf-trend-4h-30d`, exactly the TSMOM benchmark rule), Gold Regime (`tf-gold-regime-4h`, new family `gold_regime`) and Momentum Rotation gold ↔ S&P 500 (`tf-rotation-4h-60d`, new family `tradfi_rotation`, long only). The new families are outside `FAMILIES`, so the lab's search, bandit, screener and explorers are unchanged. The lane is an independent set of sleeves in the same manifest and bot (outside the crypto slots and whitelist cap; crypto strategies never get these pairs; the crypto research universe excludes them), at exploration risk × a BTC-correlation scale (≤ 1). Entries only while the underlying market is open (NYSE hours with 2025–2027 holidays/early closes, gold Globex hours); exits and exchange stops 24/7. Every account limit applies unchanged; the lane adds stricter ones (≤ 2 positions, ≤ 0.5 % at stops) and a circuit breaker for orders/stops Bybit refuses. Availability is read from the bot's whitelist (10 min on the pairlist before "unavailable", two misses before a tradable instrument is dropped, daily re-probe); a TradFi execution test (entry → exchange stop → exit) runs once the lane is confirmed. A trade keeps its own plan after a restart or with the lane off (`closing`). Forward book as hypothesis TF1 only with `TRADFI_FORWARD_BOOK=1` (default off: a failed forward test would mark the v3 recording `partial`); the lab downloads TradFi candles apart from the benchmark/H1. A walk-forward on Bybit candles is not possible yet (≈ 6–8 months of history against the 120-day warm-up + training + test quarters). Switch: `TRADFI_ENABLED=0`. `HEALTH` adds `tradfi=[…]`. Doc: `docs/TRADFI.md`. Tests: `tests/test_tradfi.py` (43). Adding strategies during the observation period is the owner's explicit decision; the merge restarts the bot and needs his OK.
## 2026-11-23 — docs: DECISIONS amended before the first v3 record; H7 (Elliott waves) frozen v1.0
`docs/DECISIONS.md` records the round-2 rules agreed with ChatGPT before the first stored v3 record: ledger checks at common checkpoints and late publication (§3), the `partial` recording status (§3), eligibility computed from the current V3_START (§4), composition and coverage by daily book snapshots (§5, §6), Holm across the three confirmatory claims A, B and H1 at each look (§7), and the limit of the calibration (§8). `docs/H7_ELLIOTT.md`: the Elliott-wave event study, pre-registered as v1.0 (S0 of the analogues, executability on the actual entry, an explicit fill and gap model, MDE for two dependent groups, σ from placebo trades without the signals' outcomes). Code for H6/H7 only after the 03.01.2027 window and with the owner's OK. Documentation only.
## 2026-11-23 (ChatGPT review, round 2) — forward v3: a return to the book never changes a past day of Q1
The schedule kept only the first and last time a strategy was in the book served to the lab and treated everything between as scheduled. The lab re-tests every entry from its freeze, so a strategy that left the book and returned a week later had the days in between published and, by the old rule, counted in line A: the composition of past days changed after the fact (DECISIONS §5). Now the server keeps an immutable daily snapshot: per strategy the UTC days it was served on, and the days on which any book was served. A strategy is scheduled for day d when it was in the book on d and on d+1 (both books keep promising strategies by sets from results up to d−2; a day without any lab run keeps the previous day's book). `forward3.composition` gives the scheduled Q1 members of a day; values published outside the schedule are a diagnostic (`q1_off_schedule_days`) and never enter line A. Coverage uses the same days; for a strategy that never left the book nothing changes. Eligibility for the primary sample is now computed from the freeze and the current `V3_START` (stored flags follow it), so a moved start date cannot leave early strategies in the sample. DECISIONS §4–§6 amended. Tests: `test_a_return_to_the_book_never_changes_a_past_day_of_q1`, `test_a_day_without_any_lab_run_keeps_the_previous_book`, `test_moving_v3_start_moves_every_stored_eligibility_flag`.
## 2026-11-23 (ChatGPT review, round 2) — forward v3: a refilled gap is neither counted twice nor a repeating revision
A day without a full candle set is `missing` and the next valid day carries both days' change as a `jump`. If a later run had the missing day's candles (e.g. after the lab's candle cache was rebuilt), the ledger published that day late while the jump kept its value, so the missing day's change was counted twice, and every later run counted the jump day as a revision. Found with a test before any v3 record existed. Now a later run is checked against published days at common checkpoints (days valid in both): the same total split differently is not a revision, a different total is (counted, the published value kept). A missing day is published late only while no later day is published; otherwise it stays missing and is listed as `refilled`. New days are appended only after the last published valid day, which the run must also have (`anchor_missing` otherwise). DECISIONS §3 amended. Tests: `test_a_refilled_gap_is_neither_counted_twice_nor_a_repeating_revision` (import → refill → two more imports: cumulative value exact, `missing`/`jump` kept, 0 revisions), `test_a_real_divergence_behind_a_refilled_gap_is_still_a_revision`, `test_a_run_that_lost_the_anchor_day_appends_nothing`.
## 2026-11-23 (ChatGPT review, round 2) — forward v3: a partial import is visible and never looks healthy
The v3 recording status said `ok` when some results of an import carried a stored v3 record and others had failed: a v3 record the lab could not build was only a count in `/api/forward`, and a forward test that failed as a whole (`ok=False`) was not seen by the v3 status at all. During weeks without the owner, a strategy whose record kept failing would only have shown up later as lower coverage. Now the status is `ok` (every result that should carry a record did), `partial` (some failed; `last_partial` moves, `last_ok` does not) or `error`; failed forward tests count. Red flag `v3 partial F/N` for the last import, `v3 > 24h` when no import was fully successful for a day; the `HEALTH` line adds `failed F/N`. Monitoring only. Tests: `tests/test_forward_v3.py::test_a_partial_import_is_flagged_and_never_counts_as_fully_ok`.
## 2026-11-23 (audit A2) — a working limit entry is not a position without an exchange stop
The `HEALTH` check flagged a trade without a stop order on the exchange 180 s after `open_date`. A maker entry can wait up to 12 minutes (`unfilledtimeout`), and Freqtrade places the exchange stop once the entry has filled, so a slow fill could raise a false red flag (and a false push to the owner during his absence). Now a trade whose entry order is still working with nothing filled is not counted until 15 minutes (then it is reported as stuck), and the 180-s grace runs from the fill (`open_fill_date`, else the entry order's fill time, else `open_date` as before). Monitoring only. Any filled amount is a position: a partially filled entry is checked from its first fill (ChatGPT's review of 23.11). Tests: `tests/test_health.py::test_a_working_limit_entry_is_not_a_position_without_stop`, `::test_a_partially_filled_entry_without_stop_is_never_hidden`.
## 2026-11-23 — forward v3 recording: record now, judge later (audit F1 with ChatGPT)
The v2 forward test books closed trades on their close day and drops trades still open at the data end, which tilts every comparison against trend strategies (the benchmark, H1); its top quartile is re-ranked over the whole population at every import, so a new high-score strategy rewrites past Q1 results; and the book keeps "promising" strategies by results that include the day being decided. The rules of v3 are fixed in `docs/DECISIONS.md` before any decision-relevant result (HEALTH 22.11 20:45 UTC: too_early, 2.2 days, benchmark 0 trades). From this deploy the system **records** what v3 needs; the v3 verdict is computed later from these records, and nothing shows v3 returns until then. The v2 verdict and everything shown today are unchanged.
- Lab (`research/marks.py`, `shadow.py`): each frozen strategy's value per **complete UTC day**, from the first full day after its freeze: an open position at its liquidation value (move since entry, minus entry costs, minus the cost of leaving now: exit fee and 5 bp), a closed trade at its realised result, so funding (only its total is known) lands on the close day and is reported as `unallocated`, never spread backwards; a close on a day without candles is realised on the next valid day. A force-exit at the data end is never a realised result. A trade opened after the freeze on its partial day enters at its liquidation value at that day's close. A day without every candle of every pair is `missing` (not 0), and so is every day of a trade that cannot be valued; the next valid day is a `jump`. Each result carries `format: 3`, `exchange`, `code_sha` (the workflow now passes `GITHUB_SHA`) and the Freqtrade version; a failure to build v3 is sent as an error, never dropped.
- Server (`forward3.py`): an append-only ledger per strategy — a published day never changes; a run that disagrees is counted as a revision. Q1 membership is decided once at the freeze from the scores of every eligible experiment frozen in the 30 days before (75th percentile; fewer than 40: `burn_in`). The book served to the lab is recorded as the coverage denominator. v3 diagnostics (records, Q1 members, coverage, missing days, jumps, revisions; no returns) are in `/api/forward` → `v3` and in the `HEALTH` line. The recording has its own status: `last_ok` moves only when a v3 record was stored (a fresh v2 import proves nothing about v3); red flags `v3 error` (the last attempt failed in the lab or on the server) and `v3 > 24h`.
Research side only: no trading decision reads any of it. Changes after ChatGPT's review of the published branch (23.11): closes on missing days carried, freeze-day positions valued at the boundary, unvaluable trades make days missing, the recording status, the source rule by format. Tests: `tests/test_forward_v3.py` (liquidation value long/short at 1x and 3x, sum equals `real_pnl`; a published day does not change when an open trade closes later; only complete days from the first full day; a freeze-day position enters at its boundary value; a close on a missing day is realised on the next valid day; an unvaluable trade makes its days missing; a stalled or failing v3 recording is a red flag while v2 arrives; a gap is missing and the next day a jump; funding on the close day; force-exit never realised; the shadow record carries v3 and its provenance; revisions kept out; a missing day may be published late; Q1 decided once from earlier freezes; burn-in; a new high-score strategy does not rewrite Q1 history; a strategy leaving the book keeps its days; a failed re-test stays in the coverage denominator; v3 leaves the v2 verdict unchanged).
## 2026-11-23 — the book keeps promising strategies by the set of two days before (condition 1)
`forward.book` kept forward-promising strategies (p_pos ≥ 0.8, ≥ 10 trades) by the leaderboard of the last import, which includes the current day. A strategy that did badly on day D could be dropped before any run covered day D completely, so whether day D was observed depended on day D's own result. The promising set is now recorded per day and the book uses the one from two days earlier, so retention on any day uses only information from before that day. Until such a record exists (the first two days after this deploy) the current set is used, which is why the primary v3 sample starts on 25.11 (`forward3.V3_START`). Which strategies get re-tested changes slightly; nothing that trades. Test: `test_the_book_keeps_promising_strategies_by_the_set_from_two_days_ago`.
## 2026-11-23 — forward evidence is Bybit data only; a stalled forward test is a red flag
When the Bybit relay is unavailable, `lab-prep` switches a whole run to OKX candles and the forward test follows the plan. Its results did not say which exchange they came from, and the newest result of a strategy replaces the previous one, so a fallback run would have replaced Bybit forward records with OKX prices. This has not happened (every lab import since 20.11 was on Bybit; ChatGPT confirmed run 45048047056 used the relay): it is a guard, not a fix of a distorted record. Results on another exchange's data are ignored (they never replace a record, `tested_until` does not move) and counted as `ignored_other_source`. The rule follows the result format, not a date: a format-3 result without `exchange` is of unknown source and ignored; older results (the lab code before this deploy carries neither) are accepted by the explicit migration rule and counted as `legacy_source`. `last_accepted` records when Bybit forward evidence last arrived, and the red flag `forward > 24h` fires when it is older, even while lab imports look fresh (a failed shadow job used to be invisible). Tests: `tests/test_forward_v3.py` (an OKX run never replaces Bybit evidence; the source rule follows the result format; a stalled forward is a red flag).
## 2026-11-22 (late) — `docs/DECISIONS.md`: forward-test rules v3 fixed before the data
The rules agreed by the owner, Claude and ChatGPT after the F1/F2 review, committed before the code that records v3 is deployed and before any decision-relevant forward result: the measurement (liquidation value per complete UTC day, funding when known, missing days, append-only ledger), Q1 decided once at the freeze, the equal-weight shadow portfolio with weights from information before each day, coverage ≥ 95 %, fixed looks at 90 and 180 valid days with α 0.01 + 0.04 and calibrated critical values (no positive verdict before the calibration), `negative_read`/`not_working` as operational verdicts, the research-vs-benchmark line as its own paired test, the separate H1 line, and the calendar (primary sample from 25.11.2026, owner's decision to deploy before his absence). v2 stays visible as a diagnostic. Documentation only.
## 2026-11-22 (audit F2) — every hypothesis says which data it has already seen
Re-reading the history that chose a configuration never makes that history clean. TSMOM became the benchmark and the core because it was the only family not losing on the lab's out-of-sample windows (the last 360 days before each run), so PLAN B4's one-off read of a "sealed last 12 months" would confirm what H1 was selected on. The H1 legs, the benchmark and the owner's systems now carry a `provenance` block: how the configuration was chosen, which periods it has seen (from–to) and the rule that its clean evidence is the forward test from its freeze only; an earlier period can reject, never confirm (as `clean_oos`). Documentation only: the importers ignore the block, no id is re-frozen and the demo core is unchanged. Nothing under `src/**` changes, so merging does not redeploy the bot. Tests: `tests/test_provenance.py` (every hypothesis, benchmark and owner file declares it; the imported records and the core are unchanged).
## 2026-11-22 (audit) — account caps count a new entry at its sized risk
`confirm_trade_entry` added a new trade at its sleeve's nominal risk, but `custom_stake_amount` sizes it up to 1.5× by conviction and may round a small stake up to the exchange minimum (another ≤ 1.5×). Near the 8 % / 4 % / 3 % caps one entry could pass them by up to ~0.1–0.2 % of equity. The new entry now counts at the larger of its nominal risk and its sized risk (order amount × stop distance), so the caps only get stricter. Open trades are unaffected. Tests: `tests/test_audit_risk.py`.
## 2026-11-22 (audit) — forward verdict counts observed days, not calendar age
A strategy leaves the forward book (no more re-tests) 60 days after its freeze. Its forward record used to be deleted at that moment, so the 90-day rule could never be reached. Keeping the records (now 120 days after the freeze) is not enough on its own: `forward_days` was the calendar age of the oldest freeze, so at day 90 a cohort that had been observed for only 60 days would get a final "works"/"not working". Now every result carries `tested_until` (the lab stamps its test time; the server falls back to the import time). The rule counts *observed* days: the time covered by at least one top-quartile strategy under test. The calendar age is reported apart as `calendar_days` and decides nothing. The daily series weighs equally the strategies under test that day: a strategy no longer tested or not yet frozen is not a zero. The benchmark is compared on the same observed days only. What is tested is the continuous research process, each strategy over its 60-day book life, not a fixed cohort over 90 days. Re-testing is unchanged (60 days, ≤ 160 strategies), so there is no extra lab load. Tests in `tests/test_forward.py`: observation stops at day 60 while the calendar says 90 (no final verdict, with and without the stamp); a continuous process reaches 90 observed days; no dilution by stale records; benchmark on the same days; lab runs every 3 days through `apply`.
## 2026-11-22 (audit) — a missing alpha over BTC no longer passes validation
The `market_alpha` gate (OOS profit must not be just the BTC move) was skipped when the alpha could not be measured. BTC candles were downloaded only for `rel_strength`; for every other family the gate depended on whether a BTC file at the base timeframe happened to be in the cache and covered the OOS window. A data gap therefore passed as a successful alpha test, and a short book in a falling market could validate. Now BTC is downloaded with every experiment at its own timeframe, the split reads that file, and a missing alpha fails the gate (exploration is unaffected: it never needed alpha). This only makes a research gate stricter; nothing changes in live trading or for open positions. Tests: `tests/test_audit_alpha.py`; four older tests that relied on the skip now carry a measured alpha.
## 2026-11-22 (audit) — the Bybit keys reach the trading bot only
The supervisor read `BYBIT_API_KEY` / `BYBIT_API_SECRET` but left them in its environment, and every child (the public web server, the manager, research workers, the self-test) was started with a copy of it. No endpoint exposed them, but the internet-facing process held exchange keys it never uses. The supervisor now removes them from its environment and passes them only to Freqtrade (`FREQTRADE__EXCHANGE__KEY/SECRET`, also on its restarts). Trading is unchanged. The OIDC lab endpoints were checked as well: RS256 against GitHub's keys, audience `aitrader-lab`, issuer, `exp`/`iat` required, this repository, `refs/heads/main` only, and no `pull_request_target` workflow; nothing to change. Tests: `tests/test_audit_secrets.py`.

## 2026-11-22 (evening) — demo always in the market: TSMOM core, active/precise lanes, no daily stop on demo
These are the owner's decisions; they change what trades on demo, not the evidence. The forward book still judges every configuration separately.

**Why.** No entry signal from 21.11 18:00 UTC on (~20 h). All of the last 10 entries were shorts of trend strategies; after the market turned up they had nothing to enter. No limit blocked anything: the daily loss limit, the kill-switch and portfolio refusals never fired.

**Demo core.**
- The pre-registered TSMOM set on 4h, 15 coins, always in the manifest at exploration risk:
  - `core-tsmom-4h-30d` (the benchmark's configuration);
  - `core-tsmom-4h-12d` and `core-tsmom-4h-84d` (the H1 legs).
- No strategy row, so no rotation or retirement. It goes first on a shared coin; its coins are kept on the whitelist; delisted coins are still excluded.
- It is in a position whenever a coin's momentum is beyond ±0.5 σ.

**Exploration lane split by trading frequency.**
- Half the slots go to active strategies (15m/1h, frequent trades), half to precise ones (2h–12h, rare trades).
- A candidate competes only within its lane. A lane below its share may take the slot of a sleeve from a lane above its share that has not earned its place (≥ 10 trades, PF ≥ 1.1).
- Until now autopilot rules let the slow 2h–12h finds displace everything else.

**Daily loss limit off on demo** (`daily_loss_limit` 0, env `DAILY_LOSS_LIMIT`). It must be on again before real money (PLAN stage D). The 25 % kill-switch stays as protection against a runaway defect.

## 2026-11-22 (evening) — janitor, H1 in the shadow, 3D office off auto-deploy
**Janitor: everything that grows now has an owner.** Owner's rule: the system must stay autonomous and delete its own garbage.
- **Hourly:**
  - rotated Freqtrade logs (keep 2);
  - temp files older than 24 h;
  - half-written atomic files older than 1 h;
  - in remote research mode, leftovers of research that once ran on the server (jobs, downloaded candles, Freqtrade result folders older than 2 days; the folders themselves stay);
  - the registry WAL is folded back.
- **Daily:** events older than 30 days (7 when the disk is < 20 % free). Below 10 % free, also the charts of candidates no live strategy shows; verdicts and parameters stay.
- **Lab:** keeps 14 days of batch files in the repository. Older ones stay in git history and in the live registry; in the tree they only slowed the server's start-up import and grew the image.
- **Reporting:** an hourly `DISK` log line: folders, largest files, registry main/WAL/free, table sizes, the container's own disk and `/tmp`, and what the janitor freed so far.

**H1 in the shadow** (`research/hypotheses/`, pre-registered):
- legs: TSMOM 12 and 84 days on 4h; the 30-day leg is the benchmark. Same construction, nothing optimised, same 15 coins.
- Forward book only: frozen at first import, never a strategy, never traded, never promoted.
- Reported apart from the research verdict as `forward.hypotheses.H1`, with H1 vs the benchmark, and as a row in the control room.
- 7/90 days as first planned fall outside the family's 4h limits (72–504 bars).

**3D office off auto-deploy:**
- `railway.json` no longer redeploys (and restarts the bot) for `src/aitrader/web/static/hq*`; such changes go live with the next approved deploy. On 22.11 two 3D deploys restarted trading.
- `CLAUDE.md` gives every Claude session the observation-period rules.

## 2026-11-22 — final patch before 2–3 weeks of observation (reviewed with ChatGPT)
Every trade now follows the strategy that opened it, and re-used out-of-sample data can no longer count as independent evidence.

**Execution: changes live behaviour only towards each trade's own rules**
- A trade whose strategy was rotated out (`closing`) or lost the coin now gets that strategy's own exit signal and ATR. The bot no longer evaluates another strategy's exit signal for it, which caused the `User denied exit` loop on XRP.
- A tagged trade never borrows another strategy's stop, target or holding time. `sleeve_for_trade` used to fall back to the coin's current owner. Each trade now stores a snapshot of its plan (strategy, parameters, timeframe, entry ATR) in Freqtrade's per-trade custom data, so the plan survives restarts.
- A higher-timeframe trade without its own candles yet leaves its stop where it is. Before, it used the bot's 15m ATR, and Freqtrade never widens a stop again. The candles of such trades are now requested as informative pairs.
- Manager:
  - at start it no longer overwrites an existing manifest with a trade-less one;
  - while the bot API is unreachable it neither rewrites the manifest nor makes kill-switch, daily-limit or rotation decisions.
  - Before, both cases dropped the `closing` strategies for at least one 120-second cycle.
- Affected: open trades of rotated-out strategies (e.g. XRP trade 13 on 21–22.11). Their closed results stay attributed to the strategy that opened them.

**Evidence: gates only stricter, research side**
- `clean_oos` is False for refinements and revalidations, so they can reject but never validate. Refinements passed 38 of 79 (48 %), fresh searches 26 of 305 (9 %). All 12 best scores were refinements or screener finds.
- Parity is now judged on the primary coin:
  - the bot's trade count against the engine's trade rate over the same time, and PF on the same coin;
  - other coins are reported apart, as transfer rather than parity.
  - First 3-year run (45005077485): signals matched on all 15 configurations (0.92–1.10×); 5 of 15 show a money gap on their own coin; the added coins made −244 on 1 944 trades.
  - The old pooled check had reported 11 of 15 as "broken". The control-room alarm now names what differs.
- Research pairs are ranked on regime scores measured before the walk-forward test windows (`scanner` `pre_oos`). The last 60 days lie inside the last test window.

**Observation**
- Disk:
  - usage history, MB/day and days to full;
  - hourly breakdown by folder, largest files and the registry's main/WAL/free pages;
  - table sizes and a `wal_checkpoint(TRUNCATE)` every 6 h.
  - The disk grew ~145 MB/day on 21–22.11 and the source was not measured.
- A `HEALTH` line next to `STATUS` every 5 min:
  - positions, positions without an exchange stop, risk at stops;
  - lab import age, disk and its forecast, forward-test summary;
  - red flags.
- `PROJECT_STATUS.md` cut to the current state; history moved here.

Tests: `tests/test_trade_plan.py` (scenarios 1–4: own exits, foreign exits never, restart keeps the plan, API down keeps the manifest), `tests/test_evidence_reuse.py` (5–6: re-used OOS never validates, like-for-like parity, pairs from before the test windows), `tests/test_health.py`.

## Until 2026-11-22 (moved from PROJECT_STATUS.md)
### Original brief vs. implementation
| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Monitor markets, find opportunities | ✅ | Lab scans **Bybit** USDT perps (via the EU relay; OKX fallback) with VolumePairList and scores trend vs. mean-reversion per pair. The server receives the universe and the scores |
| 2 | Research, **develop**, test, optimise multiple strategies | ✅ | **6 families**: EMA trend, Bollinger mean reversion, Donchian, squeeze, **time-series momentum (vol-scaled)** and **funding-rate crowding reversal**, plus structural genes. A UCB bandit, learnings (A/B) and refinements of promising strategies choose the next experiment |
| 3 | Entries, SL, TP, sizing and exits optimised together | ✅ | ATR stop, R-multiple TP, trailing, time exit and conviction-weighted risk sizing in one parameter vector |
| 4 | Realistic validation, costs, OOS, overfitting control | ✅ | Walk-forward OOS, fees + slippage + funding, 2× cost stress, ±10% parameter perturbation, Monte Carlo and WFE gates. **Deflated Sharpe counts every trial of the last 90 days** (`research/ledger.json`), so continuous searching cannot inflate significance |
| 5 | Execute and manage trades on Bybit Demo, controlled experiments | ✅ verified | Execution test passed: entry → **exchange stop-loss** → exit. Exploration sleeves trade at 0.1% risk |
| 6 | Analyse, learn, promote only after independent validation | ✅ code / ⏳ trades | Learner (pair exclusion, MFE, time exits, side asymmetry, gate failures) with A/B pruning; every rule needs statistical evidence (see "Evidence discipline"). Lifecycle: exploration → incubation → forward demo evidence → production. Revalidation every 14 days runs in the lab; a failed one retires the strategy |
| 7 | Web terminal | ✅ live | **Control room** (primary, desktop + phone): capital curve, positions with protection state, forward-test verdict, 4 live lab runners, results with fold squares, bandit, gates, lifecycle, goals, readiness, log, learnings, closed trades. **3D HQ v3** at `/hq`: real data on every screen (live 1h candles with entry/stop/target, live GitHub hyperopt epochs, fold results, gates, bandit, market map, goals). Company mission board, stand-up meetings built from real numbers, GitHub-lab cloud with data beam, expressive characters. Rendered headlessly on every UI change (`hq-preview` workflow, screenshots in `docs/preview/`, fails on JS errors) |
| — | Cloud, independent of your PC | ✅ / ⚠️ | Railway **trial** credit runs out in about 15 days. Hobby is needed for indefinite operation |
| — | GitHub + PROJECT_STATUS | ✅ | CI green with the real Freqtrade image; 113 tests |

### Best strategies first + the owner's systems (2026-11-21, 22:00; owner: "команда не нашла мои стабильные EMA-системы, торгуют не лучшие")
**Finding.** The company *did* find such systems: the last screener run evaluated ~1.1 M variants; 84 configurations on 2h–12h passed all seven autopilot checks, 36 beat the decoys (10 EMA cross, 17 MACD; 3-year PF 1.4–8). But until 2026-11-21 17:14 UTC the bot's walk-forward replicated them with its *own* exits (break-even ratchet at +0.5 R, TP 5 R instead of 1.5–2 R): 28 of 36 collapsed to PF 0.15–0.6 on the very months the engine shows profitable, were rejected, and the demo lane filled with hyperopt candidates (PF 1.1–1.5). The exact-exit fix (`exit_mode 1`) shipped with PR #3; lab run 44933681420 (started 18:06 UTC) is the first on it, and the survivors are re-tested (`x2` ids).
**Changes:**
- **Engine ↔ bot parity check** (`pipeline.parity`): every autopilot replication is compared with the engine's 3-year record; engine PF ≥ 1.3 but bot PF < 1.0 (≥ 10 trades) = broken. If half or more of a batch (≥ 4) is broken: `PARITY ALARM` event and a red line in the control room ("дефект исполнения, а не рынок"). Today's bug would have shown up on day one.
- **Long replication for fixed configurations** (owner's, autopilot) on 2h–12h: 3 years in 12 quarterly slices instead of the last year in 4 (`replication_days` 1080, `replication_folds` 12). 3× the trades of a slow strategy (a BTC-only 6h system has ~13 trades a year) and its stability over a long distance; still a replication (`clean_oos` fails), the forward test stays the evidence.
- **Best first** (`Lifecycle.outclasses`): a candidate that is clearly better (higher evidence class, or the same class with research score ≥ 1.5× and ≥ +0.2) takes the slot of the weakest exploration sleeve that has not earned it live (< 10 trades); the moved sleeve goes back to the queue. Order of victims: placeholders, idle sleeves, then the weakest. Sleeves with ≥ 10 live trades and PF ≥ 1.1 are never moved; the margin keeps slots from flipping on noise.
- **Owner's systems** queue like autopilot finds (class 2): `research/external/owner-btc6h-ema47-76.json` (EMA 47/76, BTC 6h, stop 2×ATR, TP 2R, close on the opposite cross, engine exits) and `owner-sol15m-zscore-x2.json` (the SOL z-score with the engine's exact exits; supersedes the first import, which used the system's exits). More can be dropped into `research/external/` with `"owner": true`.
- Explorer shows the replication length and "движок → бот" PF per strategy.
- **Crowded coins go to the strongest evidence first** (PR #7, found in the 22:00 check): the manifest handed pairs out by score only, so with ≤ 4 strategies per coin and the 45-pair whitelist 5 of 24 exploration strategies had no coin (an owner/autopilot system with score 0 on BTC would lose it first). Within a stage pairs now go by evidence class, then score (manifest 19 → 20 sleeves; the rest are weak and rotate out when idle for 7 days).
First run on exact exits (44933681420): of 16 autopilot replications 6 are exploratory (PF 1.14–2.49; MACD 4h on 2 coins went from PF 0.15 to 1.14), EMA crosses on 2–4h still lose on the last year (PF 0.12–0.68) – the 3-year replication + parity check from PR #6 will tell whether that is the market or a remaining mismatch.
Honest caveat for the owner: PF 2.66 over the whole chart is the record of the best of many variants seen with hindsight; in the last run shuffled-history decoys alone passed the seven checks 32 times against 84 real configurations, so roughly 4 in 10 "stable" finds are luck-level. The forward test on unseen data decides.

### Strategy explorer `/explorer` (2026-11-21, 21:30; owner: "сделай удобный интерфейс, все стратегии, все сделки на свечах")
One simple page (link "Все стратегии подробно ↗" in the control room), read-only, works on a phone:
- list of every strategy with **research / forward / demo** numbers side by side; filters Торгуют · Ждут очереди · Все · Снятые, search by coin/family, sorting;
- one strategy in full: idea and exits in plain words, why it is in its stage, three KPI blocks (history OOS incl. alpha to BTC and "clean OOS", forward after freeze, demo), **demo trades drawn on candles of the strategy's own timeframe** (built from the bot's 15m candles; ▲/▼ entries, ● exits, yellow = still open; tap a marker for details), every trade in a table (open positions with their current result), research equity curve with fold windows, cumulative forward result, every research check with value and threshold, parameters, status history;
- API: `/api/explorer`, `/api/explorer/{id}`, `/api/explorer/candles`; dates normalised to ISO-Z (Safari-safe); polls once a minute only while visible.

### Final week: proven strategies trade together, rotation, honesty gaps (2026-11-21, 21:00; owner's request)
**Rotation by evidence** (`lifecycle._displace_for`, `evidence_rank`): the waiting queue is ranked by evidence – forward-proven (`fw-…` or ≥ 20 forward trades with PF ≥ 1.3) › autopilot › research candidate › near-miss/placeholder, then score. A full exploration lane makes room for a stronger candidate by moving out a placeholder, a sleeve with < 3 trades after 7 days, or (for an autopilot candidate) an ordinary sleeve with < 10 trades. Sleeves that earned their place live (≥ 10 trades, PF ≥ 1.1) are never moved; a rotated research candidate goes back to the queue (it did not fail), a rotated near-miss retires.
**All proven strategies trade at the same time, each on its own coins:**
- slots for proven stages 20/20 (were 6 production / 8 incubation); a family may have many proven variants on *different* coins (max 2 per coin); the 12-per-family cap applies to unproven exploration only;
- `proven_scale`: per-trade risk of proven sleeves is scaled so that with half of their coins in a trade the open risk stays within 5 % of equity (1.0 with a handful of sleeves, shrinks only when many have proven themselves) – nobody is shut out because others entered first;
- the bot keeps room for them: exploration (unproven) may hold at most 24 positions and 3 % open risk (`max_explore_trades`, `max_explore_risk`), within the account's 40 trades / 8 % / 4 % per side.
**Honesty / safety gaps closed:**
- research gate `market_alpha`: *validated* needs OOS alpha over BTC with Newey–West t ≥ 1 (from the BTC 1h candles in the lab data; not applied when missing; exploration unaffected);
- validated needs ≥ 40 OOS trades (was 25);
- **daily loss limit**: −3 % vs the UTC day's first equity reading, confirmed by two consecutive readings, pauses new entries until 00:00 UTC (the 25 % kill-switch stays);
- bugs found in review: local-mode revalidation could re-test on a random timeframe (now its own); disk slimming could drop the chart of a rejected experiment that trades as a near-miss (now kept); the gzip middleware's constructor is Starlette-version-proof; Freqtrade re-places missing exchange stops every 60 s (`stoploss_on_exchange_interval`), so no separate orphan check is needed.
Not done (needs data or an owner decision): survivorship-free universe, market-neutral sleeves, correlation-aware sizing of the whole book (tested: Sharpe +0.15…0.21, planned before real money), Telegram alerts (needs a bot token), private repo.

### Railway cost: egress (2026-11-21, 20:00; owner: "Railway eats my usage")
Usage so far: egress $0.33 > memory $0.18 > CPU $0.04 > volume ~0. HTTP logs show three egress sources: open control-room/3D-office tabs polling large JSON every 10–15 s, the lab's freqtrade subprocesses each re-fetching Bybit `instruments-info` (~0.5 MB) through the relay, and none of it compressed.
- **gzip** for `/api/*` and `/relay/*` (JSON shrinks ~5–10×); static assets and `/api/lab/backup` untouched (`web/app.py::_ApiGZip`).
- **Relay metadata cache** in the lab hook (`relayhook/sitecustomize.py`): `instruments-info` / `risk-limit` once per runner for 6 h, shared by its subprocesses; candles never cached; error answers never cached.
- **Control room** stops polling while its tab is hidden and refreshes at once when shown again. The 3D office (owner-maintained) still polls every 12–15 s while open: close its tab when not watching.
- Candle data was already cached across lab runs (prep restores the previous run's cache).
- Memory (freqtrade ≈ 450 MB + web ≈ 185 MB) is the next cost; trimming it would mean fewer pairs/timeframes for the bot, which costs learning – not done.

### Learning loop + unattended running (2026-11-21, 19:30; owner: "observe 3–5 days / 2–3 weeks without changes")
Assessment before the changes: lab chain healthy (a successful run every 2.5–3 h since 11-20 22:27; cron runs cancel themselves while a chain runs, by design), service healthy (≈0.6 of 8 GB RAM, CPU idle, self-test ok), the old `daily_sharpe` failures already fixed (last run 62/62). Weak spots for weeks without changes, now closed:
1. **Disk.** The volume was 500 MB with 230 MB used and ~20 MB/day growth (registry research detail never pruned; Freqtrade's rotating log keeps up to 110 MB) → full in ~13 days. Now: **volume 2 GB** (owner approved; resized 2026-11-21 17:05 UTC, ~2 min restart, all 8 open positions picked up), plus `storage.py` in the daily housekeeping: rejected experiments older than 3 days lose their equity curve / per-pair / exit tables / per-fold params (verdict, gates, score, params, pairs, OOS/stress/MC summaries and fold returns stay; candidates are never slimmed), only 2 rotated Freqtrade logs are kept, VACUUM after a big slim, disk usage in kv `disk` → control room warns below 20 % free and the housekeeping slims harder (after 1 day).
2. **Forward test could not accumulate.** The book was the newest 120 experiments, i.e. ~2 lab runs: each strategy was forward-tested for a few hours and dropped out (hence "118 frozen strategies, 1 forward trade"; `fw-` promotion at 20 forward trades almost never fired). Now (`BOOK_LIMIT` 160, `BOOK_KEEP` 100): research candidates (validated/exploratory, best score first) and strategies with a promising forward record (p_pos ≥ 0.8, ≥ 10 trades) keep their place for their whole 60-day book life, the rest of the room goes to the newest experiments, the benchmark is always in. Forward evidence now grows per strategy, so `fw-` promotions, refinements of forward-proven strategies and the leaderboard can work.
3. **TSMOM horizons.** The effect everything points to was only searched on 1h (lookback ≤ 21 days). Now half of new TSMOM experiments run on **4h** (lookback 12–84 days, the documented 2–12 week horizon); refinements keep the candidate's timeframe.
4. **Interim signal for the observer:** `/api/forward.vs_benchmark` and the control room show the top quartile vs the benchmark over the same days with P(research better). A direction with its uncertainty, not a verdict.
5. **Learner:** research-gate patterns need the 8 most recent experiments of a family (was 4).
Deliberately not changed: production still needs alpha > 0 (point estimate). A t ≥ 1 requirement would need Sharpe ≈ 3.5 within a 30-day incubation and block genuine edges; production on demo only changes position size, the significance test belongs to the real-money gate (alpha t ≥ 2).

### What to watch (no changes needed)
- **Every day or two:** control room "Требует внимания" is empty or only shows macro events; bot up; lab "last import" < 10 h; disk warning absent.
- **Day 3–5:** forward book shows growing trades per strategy (leaderboard entries with 20+ trades); first `fw-…` strategies may appear in "Стратегии"; TSMOM 4h experiments in the lab list; the benchmark row has trades. Demo P&L itself says little yet.
- **Week 2–3:** `vs_benchmark` above ~90 % for several days in a row = research beats plain trend; around 50 % = the search adds nothing over the benchmark; leaderboard leaders with p_pos > 0.9 and 50+ trades are the real candidates. The verdict stays "early read" until 90 days by design.
- **Red flags:** lab import older than 24 h, manager heartbeat "error", disk warning that persists a day, kill-switch.

### Evidence discipline (2026-11-21 evening, owner's request: "найти прибыльную стратегию, демо — тренировка")
Review: `claude/METHOD_REVIEW.md` and `claude/ROADMAP.md` (project docs); this is phase 0 of the roadmap.
Principle: **fast to explore, fast to protect, slow to trust.** Exploration on demo stays as wide as before (up to 24 sleeves at 0.1 % risk, the 118-strategy shadow book); what changed is how evidence is judged before anything is declared real or gets more risk. New module `evidence.py` (pure statistics, `tests/test_evidence.py`).

1. **Clean out-of-sample only (data leak closed).** The freqtrade walk-forward tests on the last 360 days, but the swing screener chooses its configurations on everything except the last 90 days (and the pooled screener filters on its last 40 %). For screener survivors and hand-found external configs those windows were already seen. New gate `clean_oos` (`validation.clean_oos(spec)`): for them the walk-forward is a **replication** with real fees and funding – it can reject, never validate. Their only clean evidence is the forward test. This also removes the effect of the Deflated Sharpe trial count ignoring the screener's 10⁶ combinations (they can no longer reach `validated`; the screener's multiplicity is controlled by the decoys).
2. **Forward verdict v2** (amended while the book had 1 completed forward trade; stricter only): decision after **≥ 90 days** (was 14), and "works" needs the daily t to reach an **anytime-valid threshold** (normal-mixture boundary: 3.26 at 90 daily observations, 2.79 at a year) because the verdict is recomputed after every lab run. Simulated on pure noise checked daily for a year: v1 declared "works" in >12 % of paths, v2 in ≤ 5 %. Before 90 days results are an early read only.
3. **Objective comparison.**
   - **Benchmark** `research/external/benchmark-tsmom-4h-30d.json`: plain TSMOM (30-day lookback on 4h, vol-scaled, exit when momentum turns, 4×ATR catastrophic stop, nothing optimised, pre-registered rationale in the file), 15 liquid coins. It stays in the forward book permanently, is reported apart from the research ranking, and is the bar research must beat. Its own walk-forward replication run is kept out of the research ranking.
   - **Alpha vs BTC.** BTC daily candles (`btc_daily`, Bybit kline, refreshed with the market context). The forward top quartile, every deployed sleeve and the readiness evidence get beta to BTC and the alpha left after it (Newey–West t). A short book in a falling market is no longer mistaken for skill.
   - **Leaderboard with shrinkage.** Forward results per strategy are shrunk towards the book mean (empirical Bayes) and ranked by posterior mean − 1 sd, so 6 lucky trades do not outrank 150 steady ones. Per-family pooled forward stats are reported too.
4. **Production needs alpha.** Incubation → eligible additionally needs a positive alpha estimate over BTC. Profitable-but-pure-beta sleeves stay in incubation and, at the time limit, retire with the reason "the market explains it: no alpha". If BTC data is missing the sleeve **waits** (a data outage never retires a profitable sleeve).
5. **Readiness: 10 checks** (was 8): + daily t ≥ 2.5 with Newey–West (trades of one day are one bet; the per-trade t stays required too) and + alpha over BTC with t ≥ 2.0. Advisory, as before.
6. **Learner acts on evidence, not streaks** (still autonomous, still A/B-tested): pair exclusion needs ≥ 15 trades, PF < 0.7 and t ≤ −2 (was: 6 trades, PF < 0.5); family exit/holding patterns ≥ 30 trades (≥ 12 losers with MFE); long/short asymmetry ≥ 20 trades per side and Welch t ≥ 2; A/B pruning ≥ 8 experiments per arm (was 3) and reports the Welch t.
7. **UI:** the forward panel shows the benchmark row, beta/alpha of the top quartile and the current t threshold; readiness shows the two new checks.

Not touched: demo-only, 1x, risk limits (8 % total, 4 % per side), exchange stops, kill-switch, the exploration lane, the decoy control. Deferred to phase 1 (needs the whole universe incl. delisted contracts): **survivorship bias** – coins are chosen by today's volume and tested on 3 years of history.

### Engine ↔ bot parity (2026-11-21, owner's request: "полностью и чётко")
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

### Position management like a careful trader (2026-11-21, owner's request)
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

### Market context + simpler control panel (2026-11-21, owner's request)
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

### Strategy Lab autopilot (2026-11-21, owner's request)
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

### Overnight review and fixes (2026-11-21 morning)
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

### Weak spots fixed (2026-11-20, 22:50)
- **Screener false-discovery control:** every holdout test gets a p-value. Survivors must pass Benjamini–Hochberg (q = 0.2) across all holdout tests of the run, and the run reports the expected number of lucky survivors.
- **New information sources** (beyond price and volume):
  - `rel_strength`: a coin's performance relative to BTC (cross-sectional momentum). BTC candles are merged on the same candle.
  - `oi_flow`: price move combined with the **open-interest** change, in two modes (confirm a breakout carried by new positions, or fade a move on collapsing OI). Research downloads Bybit OI history (`/v5/market/open-interest`, incremental, through the relay); the live bot fetches recent OI via ccxt; OI is merged as of the candle start.
  - 18 families in total.
- **One web interface in Russian:** tabs Обзор / Стратегии / Лаборатория / Сделки / 3D-офис. Strategy cards are in the style of the owner's Strategy Lab. The old `/terminal` redirects to the control room, and the company log is translated.

### Owner's Strategy Lab integrated + owner's rules (2026-11-20, 22:00)
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

### Forward test — "can this system make money?" (2026-11-20, 21:00)
The direct answer to the owner's question. **Superseded in part by "Evidence discipline" (v2 verdict: ≥ 90 days, anytime-valid t, benchmark, alpha, leaderboard).** A real edge of Sharpe 1–2 cannot be confirmed in days to weeks by any method; v1's 14-day rule was close to a coin flip.
- **Shadow book** (`forward.py`, `research/shadow.py`): every finished walk-forward experiment is **frozen** when it finishes (parameters and pairs never change afterwards). Each lab run backtests every frozen strategy (up to 120, last 60 days) on real Bybit candles **after its freeze time only**, with fees and the 5 bp/side slippage haircut. Open trades at the data end are excluded.
- It includes the weak candidates on purpose: the test is whether the research's own ranking predicts unseen performance.
- **Pre-registered verdict** (fixed before any forward data existed): the top quartile by backtest score at freeze vs the rest.
  - too early: < 100 forward trades or < 7 days;
  - early read: direction only;
  - **works** (v1): ≥ 200 trades, ≥ 14 days, PF ≥ 1.15 after costs, daily-pooled t ≥ 2.0 → **v2**: ≥ 90 days and the anytime-valid t threshold;
  - **not working**: PF < 1.0 or return ≤ 0 at that point. That would mean the search finds noise and needs new data sources (OI, liquidations, cross-sectional), not more of the same.
- **Immediate history indicator:** does a profitable first half of the walk-forward holdout predict a profitable second half?
- **Forward-proven strategies** (≥ 20 forward trades, PF ≥ 1.3 after costs, positive) become `exploratory` (`fw-…`) and can get demo capital.
- Shown at the top of the control room, as a company goal and at `/api/forward`.

### Research throughput ×4 (2026-11-20, 21:00)
`research-lab` is now `prep` → **4 parallel runners** (4 vCPU each) + `shadow` (forward test) → `merge`.
- Each runner opens with a different family (UCB rank), and its local bandit counts the run's own finished experiments.
- Deflated Sharpe is computed over every trial: the 90-day ledger plus all four runners.
- Private-repo fallback: 1 runner.

### Honest numbers (2026-11-20, 21:00)
- PF no longer shows a fake 99 without losses; the PF goal needs ≥ 30 trades.
- Infrastructure losses (cancelled runner, restart) count as `lost`, not research failures.
- Capital = the bot's USDT trading capital (≈ 49.8k). The self-test also shows the whole demo account value including other coins (≈ 168k).

### Success-critical upgrades (2026-11-20, evening)
- **Real-money readiness gate** (`readiness.py`, `/api/readiness`, HQ mission panel). It is advisory and never switches by itself. All 10 checks (8 originally, + daily Newey–West t and alpha over BTC on 2026-11-21) are evaluated on post-promotion production trades:
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

### Real Bybit research data (2026-11-20)
Bybit blocks US IPs, and GitHub runners are in the US. Probe result: a direct request from the runner gets HTTP 403, while the same request through the server relay gets HTTP 200.

How the data reaches the lab:
- The live server (Railway EU) relays **GET-only `/v5/market/*`** requests to `api.bybit.com` at `/relay/`. Tokens are 8-hour HMACs issued via OIDC; no new ports and no API keys are involved.
- Research freqtrade subprocesses load a `sitecustomize` hook that rewrites ccxt's Bybit URLs to the relay. ccxt's own proxy options conflicted.

First live run 15:44 UTC: instruments, risk limits, 1h klines and funding history were all downloaded through the relay with HTTP 200. Fallback to OKX applies if Bybit is unreachable, and no experiments run on a universe smaller than 4 pairs.

Incident: the first attempt (ccxt proxy conflict) produced 50 empty experiments. The guard above was added and that batch file removed.

### HQ staff (2026-11-20)
- **Model and motion:** motion-captured skinned characters (three.js Xbot, Mixamo rig) with idle/walk mocap plus additive nod, head-shake and slump.
- **Procedural poses** (world-axis, rig-independent): sitting, typing, talking, phone, coffee, cheering, clapping, pointing, whiteboard.
- **Clothing shader:** skin, hair, shirts/jackets by department, lab coats, ties, belts, trousers, shoes.
- **Fallback:** the procedural rig if the model can't load.

### Research lab (GitHub Actions), added 2026-11-20
1. `GET /api/lab/state` fetches learnings, revalidations due, strategies worth refining and the family bandit stats.
2. Budgeted cycle of 170 min on public repos: revalidations → ~25% refinements → UCB new searches. Live progress (stage, epoch, best in-sample) is posted to `/api/lab/progress`.
3. Merge with the 90-day ledger DSR → `POST /api/lab/import`. Results are committed to `research/imports`, `research/reports` and `research/ledger.json`.
4. The next run is chained immediately (public repo). Cron restarts serve as a watchdog.

Auth is GitHub OIDC: the server accepts only tokens of this repository's `main` branch, with no stored secret. `lab-probe` verifies this end to end (HTTP 200 on 2026-11-20).

First run, 2026-11-20: scan finished at 14:56 UTC, experiments streaming.

### Verified in production
- Self-test 6/6 (demo endpoint, auth, futures, whitelist, `Demo trading enabled for Bybit (Demo)`).
- Execution test: XRP entry 0.9543 → exchange stop 0.9315 → exit 0.9542 (−0.08 USDT fees/spread).
- First autonomous strategy trade: 13:00 UTC, DOGE long, stop on the exchange.
- Bulk batch b20261120-44725886469 (29 OOS experiments, OKX 1h): **0 validated**, 7 exploratory after a stricter re-filter.
  - Breakout and squeeze **lose OOS after costs**.
  - EMA trend and mean reversion show OOS edge but fail Deflated Sharpe, so they run as tiny-risk exploration.
- Server since the remote-research switch: research process off, no OOM. Supervisor log line: `research mode: remote`.

### Honest outlook (owner asked)
- A subjective estimate of ~35–50% chance to find a modest, robust edge, most likely trend/time-series momentum.
- Large stable returns are unlikely.
- Demo fills are kinder than live trading.
- Next levers:
  - maker/limit entries (cost);
  - funding/basis data (added);
  - 4h/1d momentum horizons (TSMOM added);
  - a portfolio of weak, uncorrelated edges;
  - time for forward evidence.

### Bugs found by real runs (all fixed, with regression tests)
userdir must exist · absolute `file:////` pairlist URL · OOM on 1 GB (now: no research on the server) · universe too small · artifact permissions · forced-entry stake · keep-alive reset · hyperopt hang (watchdog) · weak candidates (stricter gates + retraction) · placeholders blocking research · CI missing psutil.

### Signal journal + independent bets; fixes to PR #6 (2026-11-22 morning; agreed with the owner the evening before)
**Fixes found in the morning check (my mistakes in PR #6):**
- The 3-year replication failed for every 6h/12h configuration (~13 per run, incl. the owner's EMA 47/76 BTC 6h): Freqtrade only appends to cached candle files, so history older than the cache was never fetched ("no data left after adjusting for startup candles"). Now the download also prepends older candles (`download-data --prepend`), and the number of quarters is fitted to the history that really exists (`fit_folds`: 4–12; e.g. 10 for 6h if the cache starts 1200 days back).
- `replication` and `parity` were computed in the lab but dropped by the merge (`RESULT_KEYS`), so the parity alarm could not fire and the explorer showed nothing. Added.
**Observation only (no trading decision changed):**
- **Signal journal** (`ftbase._journal*`, `signals.jsonl` next to the manifest, `observe.summarize_signals`): every new entry signal (rising edge on the last closed candle, once per candle) and every entry decision (once per 15 min). Each signal gets one outcome: executed, or why not – coin held by another strategy, two signals on one candle, pause/daily stop, same-side count, exploration count, open risk, side risk, exploration risk, or "not entered" (bot limit, zero stake, order). Kept 30 days. Control room under the positions: "Сигналы за 7 дней: N, исполнено M (x%). Пропущены: …"; explorer per strategy.
- **Independent bets** (`observe.exposure`): open positions weighted by risk at their stops and the correlation of the coins' hourly returns (bot's own 15m candles, local API, every 15 min): effective bets = (Σ|risk|)² / sᵀCs (10 same-side positions at ρ 0.8 ≈ 1.2 bets), plus the share of open risk on one side. In the positions header: "≈K независимых ставок, x% риска в одну сторону".
Later (≥ 50 demo trades): each sleeve's demo vs its own backtest over the same days.
**Post-trade review "работа над ошибками"** (owner, 2026-11-22: "не закрывают ли защитные стопы сделки зря?"; `observe.judge_exit/postmortem`, every 15 min on trades closed in the last 10 days, verdicts kept 30 days): each exit is judged against its own plan in R (initial risk) on the bot's 15m candles after the exit – planned stop: did price then reach the target before going another 0.5 R against ("стоп был прав" / "цена развернулась" = a wider stop would have won), and how much worse than the stop it was filled; stop moved to break-even/profit, exit signal, time exit: replayed with the original stop and target → money the early exit saved or cost; take profit: how far price went in the next 3 days. Control-room line + "Что было после" per trade in `/explorer`. Conclusions only from ≥ 30 cases (then an A/B test in the learner, not a switch).
First facts (7 strategy trades so far): both winners closed at the take profit (+83 $, +90 $). 4 losers closed by `managed_stop` = the planned stop (the bot exits at the same level as the exchange stop, seconds earlier, with a cheaper limit order; losses 31–34 $ = the risk budget of those trades); 1 (LINK) was closed by the exchange's backup market stop at −53 $ (filled ~0.6 R beyond the stop); 1 (NEAR) by a stop moved to near break-even (−6 $).

### Needs the owner
1. A usage limit in Railway (Hobby is paid since 2026-11-20).
2. Optional: more configurations from the owner's Strategy Lab can be dropped into `research/external/*.json`; the screener already runs the same engine automatically.
3. A second Railway project `boreal-quant-demo` (empty repo) appeared at 20:29 CET, not created by this system. It spends the same trial credit; delete it if unused.

Owner decisions (2026-11-20): keep the current Bybit **Demo** API key (no rotation); make the repo public for free research compute.

### Known limitations
- Research data now comes from Bybit through the server relay. If the relay is down, a run falls back to OKX data and says so in its report.
- Backtest TP fills at candle close, not intrabar.
- Funding family: live funding candles are requested only when a funding sleeve is deployed. If data is missing, the family stays silent.
