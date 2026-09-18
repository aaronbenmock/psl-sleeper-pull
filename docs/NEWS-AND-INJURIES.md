# How news and injuries enter the recommendations

Two halves, kept separate and labeled on the dashboard.

## Half 1: machine data (automated, free)

Source: Sleeper's `/v1/players/nfl` file, which carries per player `injury_status`,
`injury_body_part`, `injury_start_date`, `injury_notes`, `practice_participation`,
`practice_description`, `news_updated` and `depth_chart_order`.

Path into the engine:

1. Daily 6:00 AM Central, the injuries job downloads the file once (the one full pull per day
   that Sleeper asks for; every other job that day reuses the cached copy).
2. It writes the eight fields for every rostered player in the league to
   `data/injuries/2026/injuries_<date>.json` and the day-over-day changes to `diff_<date>.json`.
3. The start/sit model reads today's status and applies the multiplier (Questionable 0.90,
   Doubtful 0.40, Out 0). Sleeper's own projection also drops for injured players, so the effect
   compounds mildly on purpose.
4. The waiver model skips anyone listed Out, IR, PUP or Suspended.
5. The league view counts injured starters per team and raises a signal at two or more.
6. The dashboard's "Machine data" box shows Aaron's roster with the fields and the last seven
   days of changes per player, plus a collapsed list of league-wide changes.

Limits: Sleeper's fields say what, not why or for how long. Practice designations arrive
Wednesday to Friday; Sunday morning inactives arrive about 90 minutes before kickoff, which is
after the 10:30 AM snapshot for noon games. The 6:00 PM snapshot catches them for night games.

## Half 2: synthesis (a weekly Claude task, small ongoing cost)

Path A, the one set up in this build: a scheduled task in the Claude desktop app, "PSL weekly
news synthesis", Wednesdays 12:30 PM Central. It pulls the repo, reads the derived files, does a
web news pass on Aaron's flagged players, the waiver targets and the league signals, writes
`data/synthesis/latest.md` in a fixed four-section format with sources and dates on every claim,
rebuilds the dashboard locally, and pushes.

Two conditions for path A to be zero-touch:

1. Aaron sets the task to automatic approval (run it once, approve its tools; the approvals
   stick). Otherwise every run waits for him and the synthesis stops updating.
2. `git push` works from Aaron's PC inside the task. Claude could not test this: pushing was
   outside this build's permissions. The first run tells us. If it fails, the task saves the
   file locally and says so, and path B is ready.

Path B, built and dormant: `python engine.py synthesis` inside the Wednesday Action calls the
Anthropic API (model claude-opus-5, web search, up to 8 searches) and writes the same files. It
runs only if a repository secret named `ANTHROPIC_API_KEY` exists. Adding that secret is an
approval only Aaron can grant. Cost is API credits per week, a few cents to tens of cents per
run [Likely]. Path B needs no desktop app and no push from Aaron's machine.

Either path produces the same file, so the dashboard does not care which one wrote it. The box
shows the write date and the source and turns STALE after 8 days.

## What the synthesis may and may not do

- It writes only into `data/synthesis/` (and the files the build regenerates). It never edits
  the recommendations. The engine stays deterministic and reproducible from the committed data.
- It is labeled as synthesis on the page, with its date. Machine fields are never mixed into it.
- Every web-sourced claim must name its source and date; unconfirmed items are tagged
  [Likely] or [Guessing].

## Email

Skipped on purpose. It would need SMTP credentials stored as repository secrets and adds a
second delivery path to maintain. The bookmark covers daily use, and GitHub already emails
Aaron when a workflow run fails, which is the alert that matters.
