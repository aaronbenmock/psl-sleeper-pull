# PSL Weekly Fantasy Engine

Automated weekly system for Aaron's Sleeper team (Mockstar, ValKilmersComeback) in Pretend
Sportsball League '26. It tells him who to start, what to bid on, how the league is trending,
and how accurate the projections have actually been. Everything runs inside GitHub Actions,
because Sleeper's API is unreachable from the machines Claude controls.

Live dashboard: https://aaronbenmock.github.io/psl-sleeper-pull/ (also `PSL-Dashboard.url`, a
Windows shortcut you can drop on the desktop).

## What runs, and when (Central time)

| When | Job | What it does |
|---|---|---|
| Every day 6:00 AM | Injury tracker | Pulls Sleeper's injury and practice fields for every rostered player in the league, diffs against yesterday, refreshes rosters. |
| Wednesday 10:00 AM | Weekly pull | Last week's projected vs actual, this week's lineup, the waiver wire, the whole league's rosters, matchups and transactions. Then the waiver digest with FAAB bids. |
| Thu, Fri, Sat, Sun, Mon at 10:30 AM and 6:00 PM, plus Sunday 7:30 AM | Pre-kickoff snapshot | Freezes Sleeper's projections for every player before games start, so projection accuracy can be measured honestly later. |
| After every job | Build | Rebuilds the dashboard and the weekly archive page from the committed data. No network. |
| Wednesday 12:30 PM (Aaron's PC) | News synthesis | A scheduled Claude task reads the committed data, does a web news pass, writes the synthesis box, rebuilds, pushes. |

Cron lines are in UTC and every job is listed twice (CDT and CST). The script checks the real
Central time and runs only the job that belongs to that hour, so the November 1 clock change
cannot make the Sunday snapshot land after kickoff. Details: `docs/RUNBOOK.md`.

## Where things are

| Path | Contents |
|---|---|
| `engine.py` | Single entry point: `pull`, `injuries`, `snapshot`, `build`, `auto`, `synthesis`, `full`, `selftest`, `histbacktest` (offline historical backtest, see docs/METHOD.md section 9) |
| `data/history/` | nflverse cache for the historical backtest (gitignored, about 240 MB); `manifest.json` is committed and lists every file's URL, sha256, rows and columns |
| `tests/` | `python -m unittest tests.test_histbacktest -v`: scoring hand checks, the week-1 gate, leakage and determinism |
| `engine/` | The code (stdlib-only Python, no packages to install) |
| `reference/` | Preseason rankings v2.0, team defense rankings, 2026 schedule, week 1 Sleeper UI export |
| `data/latest.json`, `data/latest.md` | The weekly pull, same shape as v1.1 plus validation fields |
| `data/league/` | League settings, users, rosters, every week's matchups, transactions |
| `data/weeks/2026/weekNN_scored.json` | Every player's projected and actual points for each completed week |
| `data/snapshots/2026/` | Frozen pre-kickoff projections, one file per snapshot, plus an index |
| `data/injuries/2026/` | Daily injury tables and day-over-day diffs |
| `data/synthesis/` | The weekly news synthesis (markdown plus a small metadata file) |
| `data/derived/` | What the dashboard shows: lineup, waivers, league view, accuracy history, validation |
| `data/status.json` | Last result of every job; the dashboard's job strip reads it |
| `index.html` | The live dashboard, all data inlined, rebuilt after every job |
| `reports/2026/weekNN.html` | Self-contained archive page per week, works with no network |
| `docs/` | Method, runbook, and the news and injury architecture |
| `tools/make_fixtures.py` | Builds fake Sleeper responses so the engine can be tested where the API is blocked |

## How to read the dashboard

The page is split into tabs (Lineup, Waivers, League, News and injuries, Accuracy, Backtest). Every tab's content is in the HTML on load; the script only hides the others. Bookmark a tab with its hash, for example `#tab-waivers`; the old section anchors (`#keepers`, `#snapshots`, `#validation`) still open the right tab. "Show everything" expands all tabs on one page. Opening the bare URL lands on Waivers on Wednesdays and Lineup on every other day. Dark mode follows the phone's setting.

The green box at the top is the data age. It turns amber past about 16 hours and red past 26
hours, and a red banner appears. Because a job runs every day, a red banner means a scheduled
run failed or did not fire; check the Actions tab on GitHub. GitHub also emails Aaron when a
workflow fails. The job strip under the title shows the last result of each job.

Every number on the page was written into the file when it was built. Nothing is fetched
live, so a bookmarked page can be old but it can never quietly lie about when it was built.

## Method in one paragraph

Start/sit blends Sleeper's weekly projection (65%) with a baseline (35%) that starts at the
preseason model's projected points per game and drifts toward the player's season average as
games accumulate, then applies an injury multiplier. Waiver bids measure how much a player
would lift the weekly starting lineup after the add and the drop, price that at $0.60 per
point per remaining week, add a demand premium from Sleeper's add counts, and cap against the
remaining budget. Accuracy is tracked against three named baselines every week: Sleeper's own
projection (frozen pre-kickoff), the preseason VOR model, and a naive "start the highest
season average" rule. Full detail in `docs/METHOD.md`.

## Running it by hand

Normally never needed. From the Actions tab, "PSL fantasy engine", "Run workflow", pick a task.
`full` does pull + injuries + snapshot + build. Locally (no Sleeper access) only `build`
works: `python engine.py build`.

## Version history

- v1.0, v1.1 (2026-09-16): weekly Wednesday pull, `sleeper_weekly_pull.py`
- v1.2 / engine v2.0 (2026-09-18): this engine. The old script name still works as a shim.
