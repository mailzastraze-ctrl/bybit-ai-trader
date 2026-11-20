# PROJECT_STATUS

_Last updated: 2026-11-20 11:30 CET (session 1)_

## Summary
**Deployed and trading on Bybit Demo** (Railway, EU West / Amsterdam, single container, volume `/data`).
- Web terminal: https://aitrader-production-cf456409.up.railway.app (basic auth, user `admin`; the password is in the Railway variable `WEB_PASSWORD`)
- Repo: `mailzastraze-ctrl/bybit-ai-trader`. Railway auto-deploys on push to `main`.

No trading results have been claimed. All figures in the terminal come from real demo fills or Freqtrade backtests.

## Verified (with evidence)
- [x] **Bybit Demo connectivity.** Freqtrade log: `Using Exchange "Bybit (Demo)"`, `Demo trading enabled`, `Bybit: Unified account`, `Wallets synced`. The self-test passed all 6 checks on 2026-11-20 10:17 UTC: config demo flag, bot API, futures and dry_run=false, authenticated demo balance (account value ≈168.7k USDT of demo funds), whitelist, and the demo log line.
- [x] The bot is `RUNNING` with the AIPortfolio strategy and 4 bootstrap exploration sleeves (8 pairs, 0.1 % risk, unvalidated defaults used as a pipeline check).
- [x] CI is green. The whole test suite runs inside the real `freqtrade 2026.10` image (strategy glue, web API, research pipeline). All 5 strategies load in Freqtrade.
- [x] The market scan (`test-pairlist` with VolumePairList, AgeFilter and SpreadFilter) runs on Bybit from Railway.
- [ ] First completed research experiment (pending: history download → hyperopt).
- [ ] First demo order filled and the stop-loss order placed on the exchange.

## Bugs found by real runs (fixed)
1. Per-job `--userdir` must exist before Freqtrade is called (found by CI).
2. RemotePairList strips `file:///`, so an absolute path needs `file:////data/...` (found on the first deploy).
3. Memory peaked at 1.06 GB against the 1 GB trial limit. Fixes: research processes get `oom_score_adj=1000` so the bot survives an OOM, plus `MALLOC_ARENA_MAX=2` and the lite profile.
4. Redeploys interrupted the first history download, so the universe ended up with only 2 pairs and research waited silently. It now forces a rescan, and the state is logged.

## Decisions
| Decision | Reason |
|---|---|
| Freqtrade 2026.10 | Native Bybit Demo, futures, stop-loss on the exchange, backtesting and hyperopt with fees and funding, REST API. |
| One bot with many sleeves (manifest) | Freqtrade supports one bot per account. Sleeves own disjoint pairs, and `enter_tag` gives attribution. |
| Single container plus supervisor | A Railway volume can attach to only one service. |
| EU region | Bybit geo-blocks the US. |
| `AITRADER_PROFILE=lite` | The Railway trial has 1 GB RAM: 1 hyperopt job, 60 epochs, 6 pairs per experiment, 15 min pause. |

## Operations
- The supervisor prints `STATUS heartbeats=… universe=… experiments=… strategies=… closed_trades=…` every 5 min, visible in Railway deploy logs.
- Kill switch: a 25 % account drawdown pauses entries for 48 h.

## Open items / risks
- **Hosting:** this is a Railway *trial* account ($5 credit, 1 GB RAM). Estimated runway is about 2–3 weeks. Long-term operation needs Railway Hobby (with a hard usage limit) or another server.
- The Bybit Demo API key was shared in chat. Rotate it and update the `BYBIT_API_KEY` and `BYBIT_API_SECRET` variables on Railway.
- Backtest take-profit fills at candle close (not intrabar).
