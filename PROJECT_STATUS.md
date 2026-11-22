# PROJECT_STATUS

_Last updated: 2026-11-22 (final patch before 2–3 weeks of observation). History: `CHANGELOG.md`._

## What runs
- **Railway** (one container, volume `/data`, EU West, Hobby plan): Freqtrade on **Bybit Demo only** (`demo_trading` is hard-required, 1x), the manager (lifecycle, learning, manifest) and the web control room. No research on the server.
- **GitHub Actions research lab** (`research-lab`, public repo, 4 runners, a run every ~3 h): walk-forward, screener/autopilot, forward test of frozen strategies. It sends compact results to the server.
- Web: https://aitrader-production-cf456409.up.railway.app (basic auth: `WEB_USER` / `WEB_PASSWORD` in Railway). `/` control room, `/explorer` every strategy, `/hq` 3D office (owner-maintained).
- No profitability is claimed. Numbers come from demo fills or walk-forward / forward tests after costs.

## Where the evidence stands (22.11)
- 0 validated strategies. "Exploratory" means it may trade at 0.1 % risk; it is not proof of an edge. Most exploratory strategies are refinements or screener finds, and those can no longer validate (`clean_oos`).
- The decision rules are written in advance (forward v2, project doc `claude/PLAN.md` §6):
  - ≈ 21.12: is everything working;
  - 19.02.2027: is the search worth its minutes against the fixed TSMOM benchmark;
  - March 2027: does the core work.
- Before 90 days of forward data everything is an early read.
- The autopilot's "also works on other coins" did not hold in the 3-year replication (−244 on 1 944 trades). On the coin a configuration was found on, the bot repeats the engine's signals.

## What to watch (no changes needed)
- **`HEALTH` log line every 5 min** (next to `STATUS`):
  - positions, positions without an exchange stop, risk at stops;
  - lab import age, disk free + MB/day + days to full;
  - forward summary;
  - `flags=` red flags.
- **Red flags:**
  - manager not `ok` / silent > 15 min;
  - a position without an exchange stop;
  - lab import > 24 h or > 20 % failed experiments in a run;
  - disk < 20 % free or full in < 14 days;
  - kill-switch or daily loss limit;
  - `PARITY ALARM` (now: half of the autopilot configurations differ from the engine on their own coin).
- **Week 1–3:**
  - forward book trades per strategy grow; the benchmark has trades;
  - control room "Требует внимания" empty or only macro events;
  - `vs_benchmark` is a direction, not a verdict.

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
