# Rules for every Claude session in this repository

The owner runs several Claude sessions on this project (trading system, 3D office). These rules keep them from breaking each other and the live demo bot.

## Observation period: 22.11.2026 → ≈ 13.12.2026
- The owner observes the system without changes to its trading logic. Decisions and dates: project doc `claude/PLAN.md` (§6) and `PROJECT_STATUS.md`.
- **A push to `main` that touches `src/**`, `ft/**`, `config/**`, `Dockerfile` or `pyproject.toml` redeploys Railway and restarts the trading bot.** Do not push such a change without the owner's explicit OK in that conversation.
- Exception: the 3D office files `src/aitrader/web/static/hq*`. They do not trigger a deploy (`railway.json` `watchPatterns`), so the 3D office can be worked on freely. Changes go live with the next approved deploy.
- Only fixes for defects that distort trades or evidence, or threaten operation, may change trading behaviour during the period. Each is its own PR with a `CHANGELOG.md` entry.

## Never
- Weaken a research gate (gates only get stricter).
- Change demo-only, 1x leverage, risk limits (8 % total, 4 % per side), exchange stops or the kill-switch.
- Switch the daily loss limit back on during the demo, or leave it off for real money. The owner switched it off on demo on 22.11; it is required before real money.
- Remove or rotate the demo core (`core-*`, files with `"core": true`) without the owner. It is his decision of 22.11.
- Add strategy families or genes during the observation period.

## Before merging
- `ruff check src ft tests` and `pytest -q` locally.
- Both CI jobs green: `Unit tests (framework stub)` and `Tests inside the real Freqtrade image`. The second is the one that matters for live code.
- A one-paragraph entry in `CHANGELOG.md`.
- `PROJECT_STATUS.md` stays one screen of current state. History goes in `CHANGELOG.md`.

## After a deploy
- Self-test in the logs (6 checks ok).
- No `Traceback` or `User denied exit` loops for 30 minutes.
- The `HEALTH` line shows `no_exchange_stop=0` and `flags=none`.
