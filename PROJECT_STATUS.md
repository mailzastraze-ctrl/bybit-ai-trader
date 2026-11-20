# PROJECT_STATUS

_Last updated: 2026-11-20 15:10 CET_

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
| 7 | Web terminal | ✅ live | **3D company HQ v2** at `/` (Three.js, PBR): 21 articulated staff (walk/sit/type/talk/gesture/coffee) with A* navigation, event-driven dialogues from real system events, live desk monitors and video wall, data-flow particles, day/night city skyline, camera tour/follow/focus. Classic terminal at `/terminal` |
| — | Framework first, verified Bybit Demo compatibility | ✅ | Freqtrade 2026.10, native `demo_trading`; self-test 6/6 |
| — | Cloud, independent of your PC | ✅ / ⚠️ | Railway **trial** (1 GB RAM, $5 credit). Hobby is needed for indefinite operation |
| — | GitHub + PROJECT_STATUS | ✅ | CI green with the real Freqtrade image; 65 tests |

## Verified in production
- Self-test 6/6: demo endpoint, auth (≈168.7k USDT demo account value), futures, whitelist, log line `Demo trading enabled for Bybit (Demo)`.
- Execution test: trade #2 XRP/USDT:USDT, entry 0.9543 (62.8 contracts, 2×), exchange stop 0.9315, exit 0.9542, −0.08 USDT (fees and spread).
- Research on Railway: data download + hyperopt run within the 1 GB limit since the memory fixes.
- **First autonomous strategy trade:** 13:00 UTC, `boot-donchian_breakout` long DOGE/USDT, filled, stop on the exchange.
- **First completed walk-forward experiment on Railway** (13:57 UTC, meanrev_bb, 4 pairs) after the watchdog fix.
- **Bulk research batch b20261120-44725886469** (GitHub Actions, real Freqtrade, OKX 1h data): 29 OOS experiments, **0 validated** (batch-wide DSR, N=29), 7 exploratory after the stricter re-filter. Findings: Donchian breakout and squeeze momentum **lose OOS after costs** (PF 0.48–0.96, DD up to 57%). EMA trend (best PF 2.32 / Sharpe 2.62 / DD 3%, 34 trades) and Bollinger mean reversion (PF 1.18–1.50) show OOS edge but fail Deflated Sharpe, so they enter the exploration lane at 0.1% risk and must prove themselves on Bybit Demo. Report: `research/reports/b20261120-44725886469.md`.

## Active self-learning (added 2026-11-20)
- **Always-on exploration:** empty exploration slots are filled with the best recent near-misses (positive OOS but failed a strict gate). If nothing at all is trading, 2 random-variant explorers start. Live evidence never stops flowing.
- **Live vs. OOS divergence:** after 20 or more trades, a sleeve whose live mean return is negative and more than 2 SE below its OOS expectation is retired.
- **Performance-weighted capital:** risk per trade × a shrunk live-PF multiplier (0.5–1.5) for incubation and production sleeves.
- **Re-validation:** every 14 days each live strategy gets a fresh walk-forward experiment on its pairs. Re-optimised versions enter as new candidates.
- **Strategy discovery:** structural genes (HTF trend filter, volatility regime) let hyperopt search 24 variants across the 4 families.

## Memory management (1 GB trial)
cgroup headroom guard before heavy jobs, adaptive research scale after OOM, `oom_score_adj` (research is killed first, never the bot), `malloc_trim`, linear-only ccxt markets, manager embedded in the web process, housekeeping and VACUUM, job-folder pruning.

## Bugs found by real runs (all fixed, with regression tests)
userdir must exist · absolute `file:////` pairlist URL · OOM on 1 GB · silent wait when the universe was too small · artifact permissions · forced entries need explicit stake handling · keep-alive connection reset during polling · **hyperopt hung for 2 h at 0 CPU** (now: watchdog kills stalled/timed-out subprocess groups, research heartbeat restart) · weak "barely positive" candidates entered exploration (now: stricter exploratory gates, re-filter retracts) · unvalidated bootstrap sleeves blocked research candidates (now: research-backed candidates displace placeholders).

## Needs the owner
1. **Railway Hobby** (with a hard usage limit) for operation beyond the trial (~15 days of credit at the measured ≈ $10/month).

Owner decision (2026-11-20): keep the current Bybit **Demo** API key; no rotation (demo funds only).

## Known limitations
- Research experiments on Railway on 2026-11-20 were mostly interrupted by redeploys (each deploy restarts the container). This is expected to stop now that development has settled.
- GitHub runners can't reach Bybit (US geo-block), so bulk research uses OKX prices as a proxy. Imported candidates must pass Bybit Demo forward tests.
- Backtest TP fills at candle close, not intrabar.
- **1 GB RAM limits Railway research.** With 17 whitelisted pairs the bot uses ~450 MB, and hyperopt (~350 MB) gets OOM-killed. The bot is protected and research scales itself down. On this tier the main research engine is the weekly GitHub batch (~1,400 of 2,000 free minutes/month). 2 GB RAM on Railway Hobby would make continuous on-server research reliable.
