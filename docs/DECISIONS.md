# DECISIONS — forward-test rules, fixed before the data

Agreed by the owner, Claude and ChatGPT on 22.11.2026 (audit F1/F2 and follow-ups). This file is the
authoritative record of the rules; the code implements them and cites the sections.

**Written before any decision-relevant result.** At the time of writing the forward test reported
`HEALTH 2026-11-22 20:45 UTC forward=[too_early, days 2.2, benchmark trades 0, P(top>bench) None]`.
No v3 return is computed or displayed anywhere until the v3 verdict code is merged ("record now,
judge later", §12). A rule here changes only for a documented measurement or data error (§11).

**Amended 23.11.2026, before the first stored v3 record** (round 2 of ChatGPT's review, owner's OK):
§3 ledger checks and late publication, §3 recording status `partial`, §4 eligibility computed from
the current V3_START, §5/§6 composition and coverage by daily book snapshots, §7 Holm across the
lines, §8 the limit of the calibration. Each is a measurement error found in review or a stricter
rule; none was seen against data.

## 1. v2 (kept for audit; computed and shown as before)
- Book: every finished walk-forward experiment is frozen; each lab run backtests it from its freeze
  on Bybit candles (60-day book life); records kept 120 days after the freeze.
- Q1: the top quartile of all accumulated records by research score, recomputed at every import.
- Daily series: equal weight over the strategies under test that day; a closed trade's result is
  booked on its close day; trades still open at the data end are dropped.
- Verdict: too early < 100 Q1 trades or < 7 observed days; early read < 200 trades or < 90 observed
  days; works = PF ≥ 1.15 and daily t ≥ the anytime-valid boundary; not working = PF < 1 or
  return ≤ 0; inconclusive otherwise.
- Known defects (why v3 exists): closed-trade booking tilts comparisons against trend strategies
  (F1); the population quartile re-ranks history (a new high-score strategy rewrites past Q1 days);
  book retention used results of the day being decided; the return sum (one 10k wallet per
  strategy) and the daily t (equal weight) are different economic models; the anytime-valid
  boundary assumes independent normal days, which nothing checked.
- From 25.11.2026 the v2 statistical verdict is not evidence for v3; it stays visible as a
  diagnostic. The existing promotion of demo strategies by their v2 forward record
  (`forward._promote`: ≥ 20 forward trades, PF ≥ 1.3) stays active: it changes demo position size
  only, and no v3 statement relies on it.

## 2. Three separate lines, three separate questions
- **A. Research Q1:** does the shadow portfolio of Q1 strategies earn? (§5)
- **B. Research vs benchmark:** does Q1 beat the fixed TSMOM benchmark (`benchmark-tsmom-4h-30d`)
  on the same days? Only B can justify the research's cost: +2 % while the benchmark makes +10 %
  is no evidence that the search adds value. B has its own paired test.
- **H1:** the pre-registered TSMOM hypothesis (§9), with its own start date, rules and verdict.

## 3. Measurement (all lines)
For a strategy `s` and a complete UTC day `d`, with the research wallet `W = 10 000`:

    V_s(d) = Σ over trades open at the end of d of
                 sign·q·(P_d − P_in) − f_in·q·P_in − h − f_out·q·P_d − h
           + Σ over trades closed on or before d of real_pnl
    r_s(d) = (V_s(d) − V_s(d−1)) / W

`q` amount, `P_in` entry price, `P_d` the day's last close, `f_in`/`f_out` Freqtrade's fee rates,
`h` the demo→reality haircut of one side (`realism.trade_cost` / 2: 5 bp of the entry notional),
`real_pnl` = Freqtrade's `profit_abs` (fees and funding included) minus both haircuts.
- An open position is worth its **liquidation value** (exit costs included); a closed trade its
  realised result. Funding is first known at the close (Freqtrade reports its total), so it is
  recognised on the close day and reported as `unallocated`; it is never spread over past days
  (a uniform spread is allowed only in a separate retrospective diagnostic).
- A force-exit at the data end is an open position, never a realised result.
- Only complete UTC days, from the first full day after the freeze to the last complete day before
  the test. Every trade opened after the freeze counts; one opened on the freeze day enters at its
  liquidation value at that day's close (nothing from before the observation is counted).
- A day without the full candle set of every pair of the strategy is **missing** (never 0). The
  next valid day carries a multi-day change and is a **jump**: kept in cumulative values, excluded
  from daily statistics. A close on a missing day is realised on the next valid day. A trade that
  cannot be valued (no size, prices or dates, or no complete freeze day to start from) makes its
  days missing.
- The per-trade days sum exactly to `real_pnl`, and every day depends only on what was known at
  its end: re-testing later never changes a published day.
- The server ledger is append-only: a published day never changes. A later run is checked against it
  at **common checkpoints** (days valid in both): the change since the previous common checkpoint
  must agree. A different total is a **revision** (counted at every run that sees it, the published
  value kept). The same total split differently is not: a gap refilled later gives D and D+1 where
  the ledger has one jump on D+1.
- A missing day may be published later only while no later day has been published. Once a later day
  is published, its jump already carries the missing day's change: the day stays missing and is
  recorded as `refilled` (publishing it would count its change twice). New days are appended after
  the last published valid day, which must be valid in the run too; otherwise the run appends
  nothing for that strategy (`anchor_missing`) and a later run continues. A correction of a data
  error is a recorded decision in this file, never automatic.
- Provenance per record: result `format` 3, `exchange` (Bybit only; other sources are ignored and
  stop the clock), `code_sha`, Freqtrade version. The source rule follows the format, not a date: a
  format-3 result without `exchange` is of unknown source and ignored; older results (the lab code
  before 23.11 carries neither) are accepted by an explicit migration rule (every lab import since
  20.11 was on Bybit; run 45048047056 checked by ChatGPT) and counted as `legacy_source`.
- The recording has its own status: `ok` (every result that should carry a v3 record did and it was
  stored), `partial` (some failed: a v3 record not built, or the whole forward test failed) or
  `error`. The last fully successful import (`last_ok`) and the last partial one are kept apart.
  Red flags: `v3 error`, `v3 partial F/N` (the last import), `v3 > 24h` (no fully successful import
  for a day). A fresh v2 import proves nothing about v3.

## 4. Q1 membership (line A)
- Decided once, when the strategy first appears in the ledger, from data that existed before its
  freeze: member if its score ≥ the 75th percentile of the scores of **every eligible experiment
  frozen in the 30 days strictly before its freeze** (weak and evicted ones included; eligible =
  finished, with parameters, not a revalidation).
- Fewer than 40 reference experiments: `burn_in`, not a member.
- Stored with threshold, score, reference size and window; never recomputed. Q1 is therefore
  "strategies above the historical upper-quartile threshold": its share may differ from 25 %; the
  threshold's drift and the admission share are diagnostics, never corrected retroactively.
- The primary sample is research strategies frozen on or after **V3_START = 25.11.2026** (UTC).
  Eligibility is always computed from the freeze and the current V3_START (stored flags follow it),
  so moving the date can never leave an earlier strategy in the primary sample.

## 5. The shadow portfolio (lines A and B)
This is a synthetic shadow portfolio, not a proven executable result on Bybit.
- `M(d)` = Q1 members with a valid published value on day `d`. `R_Q1(d) = mean over s in M(d) of r_s(d)`.
  A member without a position on a valid day contributes 0; a missing day is excluded from `M(d)`
  and counts against coverage.
- Composition and weights for day `d` use only information available before the start of `d`:
  membership is fixed at the freeze; which strategies are observed (book retention) uses the
  promising set recorded two days earlier (`forward3.lagged_promising`); a strategy joining or
  leaving never rewrites past weights.
- **Daily book snapshots.** The server records, per strategy, the UTC days on which it was in a book
  served to the lab, and the days on which any book was served. A Q1 member is **scheduled** for day
  `d` when it was in the book on `d` and still on `d + 1` (the day whose runs first value `d`). Both
  books keep promising strategies by sets recorded on `d − 2` and `d − 1`, i.e. from results up to
  `d − 2`. A day without any lab run keeps the previous day's book. `M(d)` uses only scheduled members
  (`forward3.composition`). The schedule of `d` is final once the book of `d + 1` was served.
- A strategy that leaves the book and returns later is not scheduled for the days in between. The lab
  recomputes every entry from its freeze, so it will publish those days; such values are a
  diagnostic (`q1_off_schedule_days`) and never enter `R_Q1`. A return never changes a past day's
  composition, weights or value.
- Cumulative return = Σ `R_Q1(d)` (simple sum). The cumulative value, the t-statistics and the
  comparison with the benchmark all use this one daily series.
- Line B: `D(d) = R_Q1(d) − r_bench(d)` on the common valid days.
- Diagnostics shown next to it, never deciding: PF of closed trades (`PF_closed`), PF including open
  trades at liquidation value (`PF_marked`), trade counts, beta/alpha to BTC, HAC t, lag 1–5
  autocorrelations, Q1 threshold drift and admission share, revisions, unallocated funding.
- The research book's selection of what to observe (candidates and promising strategies stay
  longer) is part of the evaluated research process. Predictable selection is not by itself a proof
  of statistical validity; the tests also assume a zero conditional mean under the null.

## 6. Coverage
- Denominator: the complete days each Q1 member was scheduled (§5, daily book snapshots, from its
  first full day), failed runs and lab outages included. Days outside the schedule never count
  either way.
- Q1 coverage ≥ 95 % is required for any verdict. The benchmark must have a valid value on every
  day used in the paired test.
- "Days" in every rule are valid common UTC days, not freeze → test time.

## 7. Looks and verdicts (fixed looks, not anytime)
- Two looks: at **90** and **180** valid days of the line. At a look: coverage met and ≥ 200 closed
  Q1 trades; otherwise `too_early`.
- One-sided significance, total α = 0.05, split **α₁ = 0.01** at look 1 and **α₂ = 0.04** at look 2.
  The critical values come from the calibration (§8), not from the normal table. **Until the
  calibration is done, no positive verdict can be issued.**
- Verdicts of line A:
  - `works` — the look statistic of `R_Q1` exceeds its calibrated critical value and `PF_closed` ≥ 1.15;
  - `inconclusive` — explicitly when cumulative > 0 but `PF_closed` < 1 while `PF_marked` ≥ 1, and in
    every case not covered here;
  - `negative_read` — at look 1, cumulative `R_Q1` ≤ 0;
  - `not_working` — at look 2, cumulative `R_Q1` ≤ 0. Operational meaning: stop or reconsider the
    research spending; it is not a proof that no edge exists.
- Line B is tested the same way on `D(d)` and reported with every verdict; the decision about the
  research's resources uses line B.
- **Three claims, kept apart.** Only B says the research adds value. A without B means "the Q1
  portfolio earned", not "the search adds return over TSMOM"; H1 is a claim about TSMOM only. At each
  look the three confirmatory claims {A, B, H1} are adjusted together by **Holm** at that look's α
  (α₁ = 0.01, α₂ = 0.04), with p-values from the calibration of §8.
- Verdicts are for the owner. No verdict switches anything automatically; the risk limits and the
  kill-switch act independently of these dates.

## 8. Calibration (a separate stage, before any positive verdict)
- Nulls: H0-A `E[R_Q1] ≤ 0`; H0-B `E[D] ≤ 0`.
- Centered stationary block bootstrap; paired days resampled jointly; mean block lengths 7, 14 and
  28 days (sensitivity); ≥ 10 000 simulations; the decision statistic at both looks with the α
  split; report the false-positive rate with its upper 95 % confidence bound.
- Lab OOS daily series and the benchmark's 3-year backtest may inform the dependence model (block
  lengths) only; they do not prove the null distribution of the future adaptive Q1.
- The result is an empirical calibration under stated assumptions, not a guarantee. The fixed Q1 and
  the two-day lag reduce bias; they do not make the adaptive research process statistically
  independent.

## 9. Line H1
- Legs `h1-tsmom-4h-12d`, `h1-tsmom-4h-84d` and the benchmark (its 30-day leg), equal weight over
  the legs; the measurement of §3.
- Starts at the legs' freeze (21–22.11.2026) **only if reproducible**: fixed parameters in
  `research/hypotheses` and `research/external` (with `provenance`), Bybit data, and the code SHA
  in the ledger. The days before `recorded_since` are reconstructed by the v3 code at that SHA;
  they count only if later runs reproduce them (no revisions). Otherwise the line starts at
  `recorded_since`.
- Looks at 90 and 180 valid days with the rules of §7 (no paired test: the benchmark is a leg;
  each leg is reported).

## 10. Calendar
- Deploy: the owner decided on 22.11 (22:47) and confirmed on 23.11 (07:24, Oslo) to deploy the
  recording now, before his absence, instead of in the 03.01.2027 window. It is a separate owner
  decision; it starts the primary sample about six weeks earlier.
- V3_START 25.11.2026: not earlier than reliable recording exists — the first v3 records arrive
  with the first lab run after the deploy of 23.11, and the two-day-lagged retention needs the
  promising set recorded on 23.11. If the first stored v3 record is later than 23.11, V3_START
  moves to that day + 2 (recorded here, before any v3 result is read).
- Line A/B look 1 ≈ 23.02.2027 and look 2 ≈ 24.05.2027 at full coverage; gaps move them later.
- H1 look 1 ≈ 20.02.2027, look 2 ≈ 21.05.2027 under the same conditions.
- 19.02.2027 (PLAN §6) stays an interim resource decision on diagnostics only (v2 and v3 data
  quality); no confirmatory verdict before the looks above.

## 11. Changing these rules
Only for a documented measurement or data error, with a test, recorded here with its date before
the next look; never after seeing results and never in their direction.

## 12. Implementation status
- From the deploy of 23.11.2026: lab daily values (`research/marks.py`), the append-only ledger, Q1
  decisions, the schedule, the two-day-lagged retention and the Bybit-only source guard
  (`forward3.py`); v3 data-quality diagnostics in `/api/forward` → `v3` and the `HEALTH` line.
- 23.11.2026, before the first stored v3 record: checkpoint comparison and `refilled` /
  `anchor_missing` (§3), status `partial` (§3), eligibility computed (§4), daily book snapshots and
  `forward3.composition` (§5, §6).
- Later, separate PRs before look 1: the v3 verdict computation from the ledger, the calibration.
