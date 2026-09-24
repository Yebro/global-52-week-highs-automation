# Entry readiness v2

Effective 2026-09-24; first frozen snapshot uses 2026-09-23 closing data.
Common-equity collection floor: KRW 100bn (1,000억원), including old watch names below it.
No market period exclusions. The old rs-price-v1 archives remain immutable.

The executable definition is entry_score.py; CONFIG is frozen in each snapshot.
Calibration: leader-case-db/entry-calibration/final.v1.json and grid.v2.json.
99 existing buy labels, including reentries and adds; 81 same-day recoveries,
92 within the next three sessions; 11/14 first entries recovered on their decision day.
34 same-day matches have a failure distance <=8%; 47 are conditional high-volatility
matches (>8%, <=16%). These are NOT 81 equally low-risk buys.
There are 367 signalled case-days out of 4,849, 286 outside original buy labels.
Non-target days are not known failed trades. No out-of-sample profitability claimed.

70 points and every hard gate required. Blocked scores capped at 59 with the cap
adjustment in the component ledger. 35 setup, 20 trend, 15 liquidity, 20 failure
distance, 10 entry position. No relative-strength percentile contributes to v2.
Same-market percentiles remain auxiliary metrics only. Signal-day failure/ceiling
levels stay fixed during the 3-session window. No signal is a brokerage order.

Models were selected using these 14 cases (winner-selection/parameter selection bias).
Reference-price adjusted historical OHLC with contemporaneous raw close*volume is
used for calibration. Current collection uses provider-adjusted OHLCV. Corporate
actions are not independently fully reconciled. Current nontrading/suspended names
are excluded; past zero-volume bars are permitted and zero OHLC is filled with
unchanged close solely for ATR calculation. Previous v1 exclusions are not altered.

Cloud source: leader-automation/leader-watch; separate state/snapshots-entry-v2-liquidity100.
Same-version comparisons only, never compare v1 scores against v2.
GitHub Actions stays at 16:00 KST plus recovery attempts on exchange sessions.
publish-only deploys saved data without a Telegram message or current quote claim.
Daily Telegram reports top 3 positive gains among continuing eligible names and
new eligible names separately, including price bounds, failure level and risk.

## Actual-turnover filter (2026-09-24)
The current universe requires at least one of the latest three exchange sessions to have reported actual turnover strictly greater than KRW 10bn. Exactly 10bn fails. Applies to candidates, watch rows, and Telegram. Daily amounts are saved for every listing, including names below the cap floor. Missing sessions use FinanceData/marcap Amount; unavailable bulk history aborts publication, individual unknowns cannot certify a pass. The original 81/99 entry recall is BEFORE this filter; no post-filter recall claim. Versioned snapshots retain the previous baseline.
