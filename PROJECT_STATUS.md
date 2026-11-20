# PROJECT_STATUS

_Last updated: 2026-11-20 12:45 CET_

## Summary
The system is **deployed and running autonomously on Bybit Demo**: Railway, EU West (Amsterdam), one container, volume `/data`. It does not trade real money: `demo_trading` is hard-required.
- Web terminal: https://aitrader-production-cf456409.up.railway.app (basic auth, user `admin`, password in the Railway variable `WEB_PASSWORD`)
- Repo: `mailzastraze-ctrl/bybit-ai-trader`. Railway auto-deploys on push (watch patterns: src, ft, config, Dockerfile, research/imports).
- No profitability is claimed. Every number comes from real demo fills or from walk-forward out-of-sample backtests.

## Original brief vs. implementation
| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Monitor Bybit markets, find opportunities | ✅ | VolumePairList/AgeFilter/SpreadFilter scan on Bybit every 12 h; trend/mean-reversion regime score per pair; research picks pairs by affinity |
| 2 | Research, **develop**, test, optimise multiple strategies | ✅ | 4 families × structural genes (HTF trend filter, volatility regime), i.e. 24 variants, each with walk-forward hyperopt. Runs continuously on Railway (Bybit data) and weekly in bulk on GitHub Actions (OKX proxy data) |
| 3 | Entries, SL, TP, sizing and exits optimised together | ✅ | ATR stop, R-multiple TP, trailing, time exit and conviction-weighted risk sizing in one parameter vector |
| 4 | Realistic validation, costs, OOS, overfitting control | ✅ | Walk-forward OOS, fee+slippage, funding, 2× cost stress, parameter perturbation, Monte-Carlo, Deflated Sharpe (whole-batch N), WFE gates |
| 5 | Execute and manage trades on Bybit Demo, controlled experiments | ✅ **verified** | Execution test passed 2026-11-20 11:26 UTC: market entry XRP filled → **stop-loss order placed on Bybit** → market exit filled. Exploration sleeves trade at 0.1 % risk |
| 6 | Analyse, learn from failures, promote only after independent validation | ✅ code / ⏳ waiting for trades | Learner (pair exclusion, MFE analysis, time-exit and side asymmetry, gate-failure analysis) with A/B pruning. Lifecycle: exploration → incubation → **forward demo evidence** → production → retire |
| 7 | Web terminal | ✅ live | **3D company HQ** at `/` (Three.js): departments = system components, workers animated by live data, clickable live panels, company log. Classic terminal at `/terminal` |
| — | Framework first, verified Bybit Demo compatibility | ✅ | Freqtrade 2026.10, native `demo_trading`; self-test 6/6 |
| — | Cloud, independent of your PC | ✅ / ⚠️ | Railway **trial** (1 GB RAM, $5 credit). Hobby is needed for indefinite operation |
| — | GitHub + PROJECT_STATUS | ✅ | CI green with the real Freqtrade image; 62 tests |

## Verified in production
- Self-test 6/6: demo endpoint, auth (≈168.7k USDT demo account value), futures, whitelist, log line `Demo trading enabled for Bybit (Demo)`.
- Execution test: trade #2 XRP/USDT:USDT, entry 0.9543 (62.8 contracts, 2×), exchange stop 0.9315, exit 0.9542, −0.08 USDT (fees and spread).
- Research on Railway: data download + hyperopt run within the 1 GB limit since the memory fixes.
- Bulk research run 44725886469 (6 jobs × 5 experiments, OKX data): scan done, jobs running.

## Active self-learning (added 2026-11-20)
- **Always-on exploration:** empty exploration slots are filled with the best recent near-misses (positive OOS but failed a strict gate). If nothing at all is trading, 2 random-variant explorers start. Live evidence never stops flowing.
- **Live vs. OOS divergence:** after 20 or more trades, a sleeve whose live mean return is negative and more than 2 SE below its OOS expectation is retired.
- **Performance-weighted capital:** risk per trade × a shrunk live-PF multiplier (0.5–1.5) for incubation and production sleeves.
- **Re-validation:** every 14 days each live strategy gets a fresh walk-forward experiment on its pairs. Re-optimised versions enter as new candidates.
- **Strategy discovery:** structural genes (HTF trend filter, volatility regime) let hyperopt search 24 variants across the 4 families.

## Memory management (1 GB trial)
cgroup headroom guard before heavy jobs, adaptive research scale after OOM, `oom_score_adj` (research is killed first, never the bot), `malloc_trim`, linear-only ccxt markets, manager embedded in the web process, housekeeping and VACUUM, job-folder pruning.

## Bugs found by real runs (all fixed, with regression tests)
userdir must exist · absolute `file:////` pairlist URL · OOM on 1 GB · silent wait when the universe was too small · artifact permissions · forced entries need explicit stake handling · keep-alive connection reset during polling.

## Needs the owner
1. **Railway Hobby** (with a hard usage limit) for operation beyond the trial (~2–3 weeks of credit).

Owner decision (2026-11-20): keep the current Bybit **Demo** API key; no rotation (demo funds only).

## Known limitations
- Research experiments on Railway on 2026-11-20 were mostly interrupted by redeploys (each deploy restarts the container). This is expected to stop now that development has settled.
- GitHub runners can't reach Bybit (US geo-block), so bulk research uses OKX prices as a proxy. Imported candidates must pass Bybit Demo forward tests.
- Backtest TP fills at candle close, not intrabar.
- Lite profile on 1 GB: slower research (1 hyperopt job, ~48 epochs, 6 pairs).
