# GitHub Pages deployment race mitigation

## Problem
`Melshayeb/aeyeing.com` runs GitHub Pages with a dynamic trigger. Two scanners (US and AU) share the same repository and both push to `main`. GitHub Pages only allows one deployment in flight at a time; when a second commit lands while Pages is still deploying, the Pages `deploy` job fails with the generic annotation:

> `deploy — Deployment failed, try again later.`

This is not a build or code error — it is a GitHub-side deploy concurrency issue.

## Current strategy (permanent)
1. **Cadence gating in `main.py`** — cron fires every 5 minutes, but the scanner exits early unless the current minute aligns with the allowed cadence:
   - **US outside active window:** every 15 minutes (0, 15, 30, 45).
   - **US active window** (18:00 Sydney → 09:30 ET): every 10 minutes (0, 10, 20, 30, 40, 50).
   - **AU (ASX):** every 30 minutes (0, 30).
2. **API-backed push guard** (`pages_status.py`) queries the public GitHub API before every push.
   - Skip push if a Pages run is `in_progress`, `queued`, `requested`, or `waiting`.
   - Skip push if the latest Pages run failed within the last **15 minutes**.
   - Skip push if we are rate-limited by GitHub API (do not push blind).
3. **Local cool-down sentinel** (`.ozmoeg_last_push`) enforces **180 seconds** between pushes.
4. **Directory lock** (`.ozmoeg_push.lock`) prevents multiple local scanners from pushing simultaneously.
5. **Overlapping Pre-Market Hourly Scan cron paused** — it duplicated the main US scanner and added extra pushes.

## Files involved
- `main.py` — `_is_us_active_trading_window()` and `_scan_allowed_minute()`
- `pages_status.py` — public GitHub API guard
- `website_updater.py` — `_git_push()` lock/throttle/API-check logic
- Hermes cron jobs `ee2455159797` (US) and `ca205d338268` (AU)

## Verification
- A normal run at 18:22 was skipped by the cadence gate.
- A `--force` run at 18:23 was allowed to scan, but push was skipped because Pages run #2030 had failed 12.7 minutes earlier.
- Latest public API check: `skip=False | GitHub Pages run #2004 status=completed conclusion=success — push ok`.

## Future improvements if failures persist
- Push only on meaningful data changes (skip when scan output is unchanged).
- Reduce artifact size further by compressing images or offloading history to a separate JSON file.
- Add a pending-commit queue so 5-minute-resolution scans are never lost.
