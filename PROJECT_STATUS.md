# PROJECT_STATUS

_Last updated: 2026-11-20 (session 1)_

## Summary
The full system is implemented and unit-tested. It is **not yet deployed**: deployment needs the GitHub repo and the Railway service (see "Next steps"). There are no trading results yet, and none are claimed.

## Decisions
| Decision | Reason |
|---|---|
| Foundation: **Freqtrade 2026.10** (Docker `freqtradeorg/freqtrade:2026.10`) | Native Bybit Demo (`exchange.demo_trading`, checked in `freqtrade/exchange/exchange.py` and `bybit.py`), futures, stop-loss on the exchange, backtesting with fees and funding, hyperopt (Optuna), REST API. |
| **One bot, many sleeves** (manifest-driven `AIPortfolio`) | Freqtrade docs: one bot per (sub)account; multiple bots on one account are unsupported. Sleeves own disjoint pairs, and `enter_tag` = sleeve id gives per-strategy attribution. |
| Timeframe 1h, USDT linear perps, isolated, leverage 3 (risk is set by the stop distance, not by leverage) | Robust signal and cost ratio, and manageable compute on Railway. |
| Single container + supervisor | A Railway volume can attach to only one service. |
| Region EU West (Amsterdam) | Bybit geo-blocks US IPs. |

## Verified
- [x] Freqtrade source (2026.10, commit 4cf0351) was read for: the demo-trading flag, Bybit futures and stop-loss-on-exchange, the RemotePairList `file:///` format, the backtest zip and `.fthypt` formats, the hyperopt loss interface, strategy callback signatures, parameter detection, the REST endpoints, env-var config overrides and the CLI flags.
- [x] 43 unit and integration tests pass locally against a Freqtrade API stub. They cover: indicators, no-lookahead checks for every family, stop/TP/trailing/time/sizing math, manifest ownership, metrics/PSR/DSR/Monte-Carlo, gates, walk-forward folds, result parsers, the registry, lifecycle transitions, learner rules, the kill switch, and a full research pipeline with a simulated Freqtrade runner.
- [ ] CI with the real Freqtrade image: runs on the first push.
- [ ] Web API test: needs FastAPI and runs in CI. It could not run locally because there is no package network.
- [ ] Live self-test on Railway (demo auth, demo endpoint log line).
- [ ] First real research experiment on Bybit data.

## Next steps
1. Push to `mailzastraze-ctrl/bybit-ai-trader`.
2. Railway: project, service from repo, EU region, `/data` volume, variables, domain.
3. Watch the build and deploy logs, the self-test, the first manifest and the first demo orders.
4. Check that the first experiment completes. Tune `RESEARCH_EPOCHS` and `RESEARCH_JOBS` to the CPU budget.

## Known limitations / risks
- Backtest take profit fills at candle close, not intrabar. That is conservative for TP and slightly optimistic for gaps.
- Bootstrap sleeves (`boot-*`) trade **unvalidated default parameters** at 0.1 % risk. Their purpose is to check the pipeline, not to make money, and they retire on their own.
- Bybit Demo has a fixed API rate limit and keeps orders for only 7 days. Freqtrade's trade DB on `/data` is the system of record.
- Research CPU use costs money on Railway. The defaults are 2 hyperopt jobs and a 5 min pause between experiments.
