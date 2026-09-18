# Runbook: what runs, how to tell it is broken, what to do

## The schedule

| Central time | Job | Cron lines (UTC) in `.github/workflows/engine.yml` |
|---|---|---|
| Daily 6:00 AM | injuries | `0 11 * 9-12,1 *` (CDT) and `0 12 * 9-12,1 *` (CST) |
| Wednesday 10:00 AM | pull (weekly digest, waivers) | `0 15 * 9-12,1 3` and `0 16 * 9-12,1 3` |
| Sunday 7:30 AM | snapshot (London-window games) | `30 12 * 9-12,1 0` and `30 13 * 9-12,1 0` |
| Thu to Mon 10:30 AM | snapshot (early slate) | `30 15 * 9-12,1 0,1,4,5,6` and `30 16 * 9-12,1 0,1,4,5,6` |
| Thu to Mon 6:00 PM | snapshot (night games) | `0 23 * 9-12,1 0,1,4,5,6` and `0 0 * 9-12,1 1,2,5,6,0` |
| Wednesday 12:30 PM | news synthesis | Scheduled Claude task on Aaron's PC, not an Action |

Every job ends by rebuilding the dashboard and committing. The workflow also runs `full` on any
push that changes the engine code, which is how the first push populates everything.

### Why every line appears twice

GitHub crons are UTC. Central time is UTC minus 5 until Sunday 2026-11-01 at 2:00 AM, then UTC
minus 6. If the Sunday snapshot were one cron at 15:30 UTC, it would fire at 10:30 AM through
October and 9:30 AM from November, harmless. But the reverse mistake, one cron tuned for CST,
would fire at 11:30 AM in September, and a late start on top of that lands after the noon
kickoffs. So each job has a cron for each offset, and `python engine.py auto` reads the real
Central time and runs only the job whose hour matches. The other cron rebuilds the dashboard
and exits. The Wednesday pull accepts both 10 AM and 11 AM so a late GitHub start never loses
the week (a second pull is harmless, and the players file is only downloaded once a day).

The time-zone rule is coded by hand (second Sunday of March to first Sunday of November) so it
works without a time-zone database. The workflow's self-test step compares it with the runner's
own database on every run and prints any mismatch.

## How to tell it is working

1. Open the dashboard. The age box is green and under a day old.
2. The job strip shows OK for pull, injuries and snapshot with recent times.
3. The Snapshots section lists entries for the current week with "still pre-kickoff" above zero
   for the Sunday 7:30 and 10:30 runs.
4. The Accuracy section's "Sleeper from snapshot" column is non-zero from week 2 onward.

## How to tell it is broken

- Red banner: no successful build in 26 hours. A run failed or never fired.
- Amber banner: the last run of some job failed but a later build succeeded.
- GitHub emails the repo owner when a workflow run fails. That email is the real alert.
- Snapshots section empty after a Sunday: the snapshot job is not firing.
- Synthesis box says STALE: the Wednesday Claude task is not running or not pushing.

## What to do

| Symptom | Likely cause | Fix |
|---|---|---|
| Red banner, no workflow runs in the Actions tab | GitHub disables scheduled workflows on repos with no pushes for 60 days | Push any commit, or click "Run workflow" once |
| A run failed with an HTTP error from api.sleeper.app | Sleeper outage or rate limit | Nothing; the next run retries. If it persists for a day, run the workflow by hand |
| A run failed inside `build` | Bug in the analysis code | Open the run log, copy the traceback into a Claude session with this repo |
| Wednesday pull ran but the record check says "unexplained" | Sleeper changed how it reports records | Ask Claude to look at `data/league/league.json` |
| Synthesis box stale but the task ran | The task could not push | Push once by hand from GitHub Desktop; then ask Claude to check the task's git credentials |
| Dashboard 404 | Pages not enabled or index.html missing | Settings, Pages, source main / root; confirm `index.html` at repo root |

## Manual runs

Actions tab, "PSL fantasy engine", "Run workflow". Tasks: `full` (everything), `pull`,
`injuries`, `snapshot`, `build`, `synthesis`, `auto`. `pull` accepts an override for the
completed week number.

Local only, never scheduled: `python engine.py histbacktest` runs the historical backtest on
nflverse data (downloads about 240 MB into `data/history/` the first time, gitignored, then about
25 seconds per run) and rebuilds the dashboard so the Backtest tab shows the result. Add
`--no-download` to use the cache only and `--no-build` to skip the dashboard. Tests:
`python -m unittest tests.test_histbacktest -v`. See docs/METHOD.md section 9.

## Costs and limits

- GitHub Actions: free for public repos. About 22 runs a week, each about a minute.
- Sleeper: the full players file (about 5 MB) is downloaded at most once per day and cached in
  `data/players/players_slim.json`; everything else is small.
- Repo growth: roughly 1 to 2 MB a week of committed data.
- Synthesis: the desktop task uses Claude credits weekly. The optional in-Action path costs API
  credits per run instead and needs the `ANTHROPIC_API_KEY` repository secret.

## The one thing Aaron must do for the synthesis

The scheduled task "PSL weekly news synthesis" lives in the Claude desktop app under Scheduled.
Set it to run with automatic approval (click "Run now" once and approve the tools it asks for;
approvals are stored on the task). If it needs approval every week, it will sit waiting and the
synthesis box will silently go stale. That would be a manual step in disguise.
