# bybit-ai-trader

An autonomous strategy research and trading system that runs 24/7 on a **Bybit Demo** account (never real money). It is built on [Freqtrade](https://www.freqtrade.io) 2026.10.

Freqtrade already does exchange connectivity, order execution, stop-loss on the exchange, backtesting with fees, funding and leverage, hyperopt, pairlists and the REST API, so this project reuses all of that. It adds the parts Freqtrade doesn't have:

| Layer | What it does | Code |
|---|---|---|
| Strategy families | 4 parameterised signal generators (EMA trend + pullback, Bollinger mean reversion, Donchian volume breakout, volatility-squeeze release). Each has **entry, ATR stop, R-multiple take profit, trailing, time exit and conviction-scaled position sizing in one parameter vector**, and they are optimised together. | `src/aitrader/families/` |
| Multi-sleeve host | One Freqtrade bot (Freqtrade requires one bot per account) runs many strategies at the same time. Each *sleeve* owns a disjoint set of pairs and has its own risk budget. It is driven by `manifest.json`, which hot-reloads. | `ft/strategies/AIPortfolio.py`, `src/aitrader/ftbase.py` |
| Research engine | Walk-forward analysis: hyperopt on a train window, then test on the unseen next window using the **same code path as live**. Costs are Bybit taker fee plus slippage plus funding. After that come a doubled-cost stress test, parameter-perturbation robustness, a Monte-Carlo bootstrap, the Deflated Sharpe Ratio and walk-forward efficiency. The result is gated: validated, exploratory or rejected. | `src/aitrader/research/` |
| Market scanner | Selects the liquid USDT-perp universe with Freqtrade's VolumePairList, AgeFilter and SpreadFilter. It scores each pair's trend vs mean-reversion affinity, and research uses those scores to pick pairs. | `src/aitrader/scanner.py` |
| Generator | A UCB1 bandit over strategy families, plus A/B testing of learned search-space adjustments. | `src/aitrader/research/generator.py` |
| Lifecycle | Stages run rejected/exploratory → **exploration** (0.1 % risk) → validated → **incubation** (0.25 %) → eligible → **production** (0.75 %) → retired. Promotion needs forward demo-trading evidence that the optimiser never saw. Production sleeves are retired on a rolling PF or drawdown breach. There is also an account kill switch: a 25 % drawdown pauses entries for 48 h. | `src/aitrader/lifecycle.py`, `manager.py` |
| Learning loop | Finds losing pairs, winners that turned into losers (MFE in R), dominant time exits, long/short asymmetry, and research gates that fail often. Each finding becomes an adjustment, which is A/B-tested and pruned if it doesn't improve scores. | `src/aitrader/learner.py` |
| Web terminal | Overview (equity, daily P&L, open positions), trades, strategies/sleeves, research, market, learnings, health, events. | `src/aitrader/web/` |

## Runtime layout (one container)

```
supervisor ─┬─ freqtrade trade (AIPortfolio, Bybit demo, futures, isolated, 1h)
            ├─ manager   (every 2 min: sync trades, equity, kill-switch, lifecycle, manifest)
            ├─ research  (continuous experiments, nice'd)
            └─ web       (FastAPI on $PORT, basic auth)
/data  (persistent volume): registry.sqlite · manifest.json · pairlist.json · trades.sqlite · market data · research jobs
```

## Deploy on Railway

1. Create a service from this GitHub repo. The Dockerfile at the root is used.
2. Region: **EU West (Amsterdam)**. Bybit blocks US IPs.
3. Attach a volume at `/data`.
4. Set these variables: `BYBIT_API_KEY`, `BYBIT_API_SECRET` (demo key), `WEB_PASSWORD`, `RAILWAY_RUN_UID=0`. Optional tuning is listed in `.env.example`.
5. Healthcheck path: `/healthz`. Generate a domain and open it with user `admin` and your `WEB_PASSWORD`.

About 60 s after start, a self-test (`python -m aitrader.selftest`) checks the bot API, futures mode, an authenticated Demo balance, the whitelist, and the Freqtrade log line `Demo trading enabled`. The result appears on the **Health** tab.

## Local development

```
pip install pandas numpy pytest   # freqtrade is stubbed for unit tests
pytest -q
docker compose up --build          # full system, needs .env with demo keys
```

CI runs the unit tests and then the full suite inside the real Freqtrade image.

## Safety

* `exchange.demo_trading: true` is fixed in `config/trade.json`. The strategy also refuses to start live if it is false.
* Research subprocesses never receive exchange credentials.
* Nothing in this repo claims profitability. Every number in the terminal comes from Freqtrade backtests or real Bybit Demo fills.
