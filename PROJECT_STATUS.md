# PROJECT_STATUS

_Last updated: 2026-11-20 16:25 CET_

## Summary
The system is **deployed and running autonomously on Bybit Demo**. It never trades real money: `demo_trading` is hard-required.

Architecture, split by load:
- **Railway** (one container, volume `/data`, EU West): only trades, learns from fills, manages the strategy lifecycle and serves the web HQ. **No heavy compute.**
- **GitHub Actions research lab** (`research-lab` workflow, public repo, 4 vCPU runners, free minutes): all hyperopt, walk-forward, stress, robustness and Monte Carlo. It sends only compact results to the server.

Links and rules:
- Web HQ: https://aitrader-production-cf456409.up.railway.app (basic auth, user `admin`, password in the Railway variable `WEB_PASSWORD`). Classic terminal: `/terminal`.
- Repo: `mailzastraze-ctrl/bybit-ai-trader` (**public** since 2026-11-20; no secrets in the repo or its history). Railway deploys on code changes only (`src`, `ft`, `config`, `Dockerfile`, `pyproject.toml`); research commits do not redeploy.
- No profitability is claimed. Every number comes from real demo fills or from walk-forward out-of-sample backtests.

## Original brief vs. implementation
| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Monitor markets, find opportunities | ✅ | Lab scans OKX USDT perps with VolumePairList and scores trend vs. mean-reversion per pair. The server receives the universe and the scores |
| 2 | Research, **develop**, test, optimise multiple strategies | ✅ | **6 families**: EMA trend, Bollinger mean reversion, Donchian, squeeze, **time-series momentum (vol-scaled)** and **funding-rate crowding reversal**, plus structural genes. A UCB bandit, learnings (A/B) and refinements of promising strategies choose the next experiment |
| 3 | Entries, SL, TP, sizing and exits optimised together | ✅ | ATR stop, R-multiple TP, trailing, time exit and conviction-weighted risk sizing in one parameter vector |
| 4 | Realistic validation, costs, OOS, overfitting control | ✅ | Walk-forward OOS, fees + slippage + funding, 2× cost stress, ±10% parameter perturbation, Monte Carlo and WFE gates. **Deflated Sharpe counts every trial of the last 90 days** (`research/ledger.json`), so continuous searching cannot inflate significance |
| 5 | Execute and manage trades on Bybit Demo, controlled experiments | ✅ verified | Execution test passed: entry → **exchange stop-loss** → exit. Exploration sleeves trade at 0.1% risk |
| 6 | Analyse, learn, promote only after independent validation | ✅ code / ⏳ trades | Learner (pair exclusion, MFE, time exits, side asymmetry, gate failures) with A/B pruning. Lifecycle: exploration → incubation → forward demo evidence → production. Revalidation every 14 days runs in the lab; a failed one retires the strategy |
| 7 | Web terminal | ✅ live | **3D HQ v3**: real data on every screen (live 1h candles with entry/stop/target, live GitHub hyperopt epochs, fold results, gates, bandit, market map, goals). Company mission board, stand-up meetings built from real numbers, GitHub-lab cloud with data beam, expressive characters. Rendered headlessly on every UI change (`hq-preview` workflow, screenshots in `docs/preview/`, fails on JS errors) |
| — | Cloud, independent of your PC | ✅ / ⚠️ | Railway **trial** credit runs out in about 15 days. Hobby is needed for indefinite operation |
| — | GitHub + PROJECT_STATUS | ✅ | CI green with the real Freqtrade image; 94 tests |

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
  - Bybit instead of OKX research data (GitHub runners are geo-blocked by Bybit);
  - cross-sectional momentum / open-interest data;
  - a real-account switch procedure.

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
1. **Railway Hobby** (with a hard usage limit) for operation beyond the trial (≈ $10/month measured; trial credit ≈ 15 days).

Owner decisions (2026-11-20): keep the current Bybit **Demo** API key (no rotation); make the repo public for free research compute.

## Known limitations
- GitHub runners can't reach Bybit (US geo-block), so research uses OKX prices as a proxy. Candidates must pass Bybit Demo forward tests.
- Backtest TP fills at candle close, not intrabar.
- Funding family: live funding candles are requested only when a funding sleeve is deployed. If data is missing, the family stays silent.
