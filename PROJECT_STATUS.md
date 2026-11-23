# PROJECT_STATUS

_Last updated: 2026-11-23 evening (demo = coin desks, monthly core off, no-entry alarm; before: TradFi lane, gold on demo). History: `CHANGELOG.md`. Forward-test rules: `docs/DECISIONS.md`. Rules for Claude sessions: `CLAUDE.md`._

## What runs
- **Railway** (one container, volume `/data`, EU West, Hobby plan): Freqtrade on **Bybit Demo only** (`demo_trading` is hard-required, 1x), the manager (lifecycle, learning, manifest) and the web control room. No research on the server.
- **GitHub Actions research lab** (`research-lab`, public repo, 4 runners, a run every ~3 h): walk-forward, screener/autopilot, forward test of frozen strategies. It sends compact results to the server.
- Web: https://aitrader-production-cf456409.up.railway.app (basic auth: `WEB_USER` / `WEB_PASSWORD` in Railway). `/` control room («Монеты»: coin desks and the owner's choice), `/explorer` the one strategy base (codes, sortable), `/hq` 3D office (owner-maintained).
- No profitability is claimed. Numbers come from demo fills or walk-forward / forward tests after costs.

## What trades on demo (23.11 evening, owner)
- **Coin desks – one experiment** (`aitrader/desks.py`): up to 30 top coins, on each coin the one tested strategy that is best on that coin (walk-forward profit per month on the coin with a drawdown discount), every desk a different strategy, trade frequencies mixed (active / medium / rare), 0.1 % risk.
  - Frozen for the whole experiment: no queue, no rotation, no retirement; open coins are filled on a later lab import. A new choice only with the owner (`DESK_EPOCH`).
  - The assignment: control room → «Монеты» (owner can pick any strategies from each coin's list of best), `DESKS` log line; per coin the live record is the strategy's record. One strategy base with codes: `/explorer`.
  - Each desk strategy also trades, as a guest, the other coins where it proved itself on history (desk owner first on its coin, ≤ 6 strategies per coin, ≤ 45 coins). By history ≈ 5 entries a day (desks alone ≈ 1: 0.4–2.5 a month per coin).
- **Monthly TSMOM core:** off on demo (owner, 23.11); stays the forward benchmark and H1.
- **Fresh start (owner, 23.11: "the previous stage failed, everything starts anew"):** the experiment started flat – the previous stage's 5 positions were closed at market at 15:56 UTC; the first desk entry followed at 16:00 UTC (BNB). The control room counts the experiment's result from its start.
- **TradFi lane** (owner, 23.11; `docs/TRADFI.md`): Bybit's gold and S&P 500 perpetuals in the same bot, entries only while the underlying market is open, ≤ 2 positions, ≤ 0.5 % at stops, 0.1 % risk × BTC-correlation scale.
  - **XAUUSDT:** only `xau-macd-12h` (MACD 11/56/10 + zero line, 12h; the Strategy Lab autopilot's best by stability + return on ~3.3 years of PAXG, decoy-controlled; not clean evidence).
  - **SPYUSDT** (S&P 500; `SPXUSDT` is a memecoin): Trend Following (the TSMOM benchmark rule) and Momentum Rotation vs gold.
  - Whether the demo account lists them: `HEALTH … tradfi=[XAU ok open, SPY …]`; the TradFi execution test runs once they are confirmed. Off: `TRADFI_ENABLED=0`.
- **Limits:**
  - no daily loss limit on demo (owner); up to 30 exploration positions / 3.5 % (all desks at once);
  - account limits stay: 8 % open risk, 4 % per side (a new entry counts at its sized risk), 1x, exchange stops, 25 % kill-switch.

## Where the evidence stands (23.11)
- 0 validated strategies. "Exploratory" means it may trade at 0.1 % risk; it is not proof of an edge. Most exploratory strategies are refinements or screener finds, and those can no longer validate (`clean_oos`).
- Pre-registered hypothesis **H1** (TSMOM 12/30/84 days on 4h; the 30-day leg is the benchmark) is judged in the forward book from 22.11. From 22.11 to 23.11 the same configurations also traded on demo as the core; demo results never replace the forward record.
- **Forward v3** (`docs/DECISIONS.md`, deployed 23.11): the system now records each frozen strategy's value per complete UTC day (open positions at liquidation value), append-only, with Q1 decided at the freeze and the composition of each day fixed by daily snapshots of the book (a later return to the book never changes a past day). Record now, judge later: no v3 return is computed or shown until the v3 verdict code exists; the `HEALTH` line shows only its data quality (`v3=[records, q1, coverage, revisions, ok age, failed F/N]`).
- **Pre-registered, not coded:** H6 chart patterns (`docs/H6_PATTERNS.md`) and H7 Elliott waves (`docs/H7_ELLIOTT.md`). Code only after the 03.01.2027 window with the owner's OK; neither becomes a trading strategy by itself.
- Calendar (DECISIONS §10): primary v3 sample from 25.11.2026; research Q1 and research-vs-benchmark looks at 90 / 180 valid days ≈ 23.02 / 24.05.2027; H1 ≈ 20.02 / 21.05.2027; no positive verdict before the calibration. 19.02.2027 is an interim resource decision on diagnostics only.
- v2 (closed trades, population quartile) stays visible as a diagnostic and still drives the demo promotion of `fw-` strategies; it is not evidence for v3. A missing alpha over BTC fails validation.
- The autopilot's "also works on other coins" did not hold in the 3-year replication (−244 on 1 944 trades). On the coin a configuration was found on, the bot repeats the engine's signals.

## What to watch (no changes needed)
- **`HEALTH` log line every 5 min** (next to `STATUS`):
  - positions, positions without an exchange stop, risk at stops;
  - lab import age, disk free + MB/day + days to full;
  - forward summary and `v3=[…]` (data quality of the v3 recording, no returns);
  - `flags=` red flags.
- **Activity:** `HEALTH … entries_24h=N (L/S) desks=[…]`; hourly `SIGNALS` line (signal journal: signals of 7 days, taken, why not) and `SIGCHECK` line (every signal on the bot's own candles since the experiment start: taken / coin busy / missed).
- **Red flags:**
  - `no entry > 6h` (the demo stopped entering); `signals not acted on N` (≥ 3 signals on the bot's own candles without an entry or a busy coin);
  - manager not `ok` / silent > 15 min;
  - a position without an exchange stop;
  - lab import > 24 h or > 20 % failed experiments in a run;
  - `forward > 24h` (no accepted Bybit forward result), `v3 error`, `v3 partial F/N` (some records of the last import failed), `v3 > 24h` (no fully successful v3 import for a day, while v2 may still arrive);
  - disk < 20 % free or full in < 14 days;
  - kill-switch or daily loss limit;
  - `PARITY ALARM` (now: half of the autopilot configurations differ from the engine on their own coin).
- **Week 1–3:**
  - forward book trades per strategy grow; the benchmark has trades;
  - control room "Требует внимания" empty or only macro events;
  - `vs_benchmark` is a direction, not a verdict.

## Runs by itself
- **Janitor** (`storage.py`):
  - hourly: logs, temp files, research leftovers, WAL;
  - daily: old events, slimmed research detail, signal journal, VACUUM;
  - harder on a low disk.
- **Lab:** keeps 14 days of batch files in the repo.
- **`DISK` log line** every hour.
- **3D office files** (`static/hq*`) do not redeploy the bot.

## Needs the owner
1. A Railway usage limit.
2. Delete the second Railway project `boreal-quant-demo` if unused (it still exists).
3. Optional: more Strategy Lab configurations as `research/external/*.json`.

## Known limitations
- Survivorship: coins are chosen by today's volume and tested on up to 3 years of history (phase B2).
- The screener runs without funding and with 2 decoy copies; its finds can only be confirmed by the forward test.
- Backtest take profits fill at the candle close; live waits at the level for 90 s, then crosses.
- Demo fills are kinder than a real book; a 5 bp/side haircut is applied.
- The repo is public: anything found is published.
- Deferred to after the observation period (audit 22.11, project doc `claude/AUDIT_2026-11-22.md`): production gate without clean OOS, coin choice on the same OOS, drawdown from closed trades only, core legs sharing one trade per coin.
