# PROJECT_STATUS

_Last updated: 2026-11-23 morning (forward v3 recording, #18 + #21). History: `CHANGELOG.md`. Forward-test rules: `docs/DECISIONS.md`. Rules for Claude sessions: `CLAUDE.md`._

## What runs
- **Railway** (one container, volume `/data`, EU West, Hobby plan): Freqtrade on **Bybit Demo only** (`demo_trading` is hard-required, 1x), the manager (lifecycle, learning, manifest) and the web control room. No research on the server.
- **GitHub Actions research lab** (`research-lab`, public repo, 4 runners, a run every ~3 h): walk-forward, screener/autopilot, forward test of frozen strategies. It sends compact results to the server.
- Web: https://aitrader-production-cf456409.up.railway.app (basic auth: `WEB_USER` / `WEB_PASSWORD` in Railway). `/` control room, `/explorer` every strategy, `/hq` 3D office (owner-maintained).
- No profitability is claimed. Numbers come from demo fills or walk-forward / forward tests after costs.

## What trades on demo (22.11 evening)
- **Core:**
  - always TSMOM on 4h, 15 coins (12/30/84 days), at 0.1 % risk;
  - pre-registered, nothing optimised;
  - in a position whenever a coin trends either way.
- **Exploration lane:**
  - 24 slots, half active (15m/1h, frequent trades) and half precise (2h–12h, rare trades);
  - rotated by evidence within each half.
- **Limits:**
  - no daily loss limit on demo (owner);
  - account limits stay: 8 % open risk, 4 % per side (a new entry counts at its sized risk), 1x, exchange stops, 25 % kill-switch.

## Where the evidence stands (23.11)
- 0 validated strategies. "Exploratory" means it may trade at 0.1 % risk; it is not proof of an edge. Most exploratory strategies are refinements or screener finds, and those can no longer validate (`clean_oos`).
- Pre-registered hypothesis **H1** (TSMOM 12/30/84 days on 4h; the 30-day leg is the benchmark) is judged in the forward book from 22.11. The same configurations also trade on demo as the core; demo results never replace the forward record.
- **Forward v3** (`docs/DECISIONS.md`, deployed 23.11): the system now records each frozen strategy's value per complete UTC day (open positions at liquidation value), append-only, with Q1 decided at the freeze. Record now, judge later: no v3 return is computed or shown until the v3 verdict code exists; the `HEALTH` line shows only its data quality (`v3=[records, q1, coverage, revisions, ok age]`).
- Calendar (DECISIONS §10): primary v3 sample from 25.11.2026; research Q1 and research-vs-benchmark looks at 90 / 180 valid days ≈ 23.02 / 24.05.2027; H1 ≈ 20.02 / 21.05.2027; no positive verdict before the calibration. 19.02.2027 is an interim resource decision on diagnostics only.
- v2 (closed trades, population quartile) stays visible as a diagnostic and still drives the demo promotion of `fw-` strategies; it is not evidence for v3. A missing alpha over BTC fails validation.
- The autopilot's "also works on other coins" did not hold in the 3-year replication (−244 on 1 944 trades). On the coin a configuration was found on, the bot repeats the engine's signals.

## What to watch (no changes needed)
- **`HEALTH` log line every 5 min** (next to `STATUS`):
  - positions, positions without an exchange stop, risk at stops;
  - lab import age, disk free + MB/day + days to full;
  - forward summary and `v3=[…]` (data quality of the v3 recording, no returns);
  - `flags=` red flags.
- **Red flags:**
  - manager not `ok` / silent > 15 min;
  - a position without an exchange stop;
  - lab import > 24 h or > 20 % failed experiments in a run;
  - `forward > 24h` (no accepted Bybit forward result), `v3 error`, `v3 > 24h` (the recording stalled while v2 may still arrive);
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
