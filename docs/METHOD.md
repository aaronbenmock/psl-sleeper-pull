# Method notes

Plain-English description of every number the engine produces. Where a rule is a judgment call
rather than a measured fact it is tagged [Guessing]; the accuracy tracker exists to replace those
judgments with measurements over the season.

## 1. Projected points

Sleeper publishes a projected stat line per player per week (yards, touchdowns, receptions, and
for defenses sacks, interceptions, points allowed and so on). The engine multiplies each stat by
this league's scoring setting for it and sums. Projected return touchdowns are excluded because
Sleeper's own displayed number excludes them (verified against the week 1 UI by v1.1).

Known gap [Certain]: Sleeper never projects three-and-outs or fourth-down stops, but this league
scores them (+0.5 and +1). Every completed week the engine stores, for all 32 defenses, the
points those two categories actually produced, so the size of the gap is a measured number on
the accuracy page rather than a guess.

## 2. Weekly expected points (start/sit)

For each player on Aaron's roster for the upcoming week:

    baseline = (n x season_average + 4 x preseason_ppg) / (n + 4)
    expected = 0.65 x sleeper_projection + 0.35 x baseline
    expected = expected x injury_multiplier

- `preseason_ppg` is `proj_ppg` from `player_rankings_v2.0_2026-09-08.csv` (the VOR model), or
  `wtd_def_ppg` from the defense rankings.
- `n` is games played so far. The "4" means the preseason model counts like four games of
  evidence, so by mid-season the season average dominates. [Guessing] on the constant; it is a
  standard shrinkage prior, not fitted.
- Injury multipliers: Questionable 0.90, Doubtful 0.40, Out / IR / PUP / Suspended 0. [Guessing];
  Sleeper's projection already reflects some injury news, so these are deliberately mild.
- A player with no Sleeper projection who is not on bye is treated as not playing (Sleeper zeroes
  out players who are ruled out).
- The lineup is filled greedily by expected points: QB, then two RB, two WR, two FLEX from the
  best remaining RB/WR/TE, then DEF. A "close call" is any starter within 1.5 points of a bench
  player eligible for that slot; the preseason boom rate (share of weeks in the positional top 12)
  is quoted as the tiebreak.

Projection source: the newest pre-kickoff snapshot of the week when one exists, otherwise the
Wednesday pull. The page says which.

## 3. Rest-of-season value (waivers, drops)

    ros = (n x season_average + 4 x preseason_ppg) / (n + 4)

Players outside the preseason file with no games: next-week projection discounted 20%. This is
the value used for every roster comparison, so a one-week matchup never drives a season-long
add or drop.

## 4. Waiver gain and FAAB bid

1. Rank Aaron's roster by `ros`. Protected: the QB1, the QB2 while the QB1's bye is still ahead
   (Josh Allen's bye is week 7), and the only DEF.
2. For each unrostered player on the wire: try dropping each unprotected player, rebuild the
   starting lineup with rest-of-season values, and take the drop that leaves the best lineup.
   `starter_gain` = new lineup total minus current lineup total.
3. If he would not start (`starter_gain` = 0), count depth value: a quarter of his edge over the
   player dropped. A second QB counts only his bye-week value (edge divided by weeks left).
   [Guessing] on both fractions.
4. Bid in dollars:

       bid = gain x weeks_left x $0.60
             x demand premium (1 to 1.5, scaled to the square root of his 72-hour add count
               divided by the hottest add on the wire)
             x 1.15 in weeks 1 to 4 (every team still holds its full $200)
       capped at 45% of remaining budget (60% when gain is 5+ points)
       no bid when gain is under 0.5 points a week

   The $0.60 per point per week is a judgment [Guessing]. It makes a 3-point weekly upgrade in
   week 2 worth about $30 before premiums, and a 5-point one about $50. As the season shortens,
   the same gain is worth less, which is right for a redraft roster and roughly right for a
   keeper roster.

Assumption [Likely]: Sleeper places every player who played last week on waivers until the
Thursday 2:00 AM run, so every listed player needs a bid on Wednesday.

## 5. League view

- Head-to-head, median and all-play records are recomputed from the matchup data rather than
  trusted from Sleeper's record field. The median game explains the 2-0 after week 1.
- All-play = your record if you had played every other team every week. Comparing it with the
  real record gives the luck signals.
- Lineup efficiency = points scored divided by the best lineup available in hindsight.
- Power = 0.6 x season average + 0.4 x projected points of the current starters next week
  (projected part only when at least 80% of a team's starters have a projection).
- Trend = slope of weekly scores, shown from week 3.
- Signals fire on: two or more injured starters (severity high for a top-4 scorer), bye crunches
  (2+ starters), hot/cold weeks (from week 2, more than 15 points or one standard deviation),
  lucky/unlucky (all-play expectation differs by a game), beating or missing projections by 15+
  a week (from week 2), 25+ bench points left last week, and trade fits (a team starting a weak
  player at a position where Aaron carries six or more).

## 6. Accuracy tracking

Three named baselines, each asked to predict every player's points for a completed week:

| Baseline | Prediction |
|---|---|
| Sleeper | Sleeper's projection, frozen in the last pre-kickoff snapshot taken before that player's team started (post-hoc Wednesday value for week 1, which predates the snapshots) |
| Preseason | `proj_ppg` from the v2.0 VOR rankings, the same number all season |
| Naive | The player's season-to-date average before that week (undefined in week 1) |

Player level, over every starter the 12 teams used that week (about 96) and over everyone
rostered (about 190): MAE (average absolute miss), bias (actual minus predicted), Spearman rank
correlation (does the ordering hold).

Lineup level, the decision that matters: for each of the 12 rosters, the lineup each baseline
would have started, scored with real points, against the hindsight-optimal lineup and against
what the manager actually started.

Also tracked: DEF bias and its structural part, pre-kickoff snapshot coverage, and post-hoc
drift (how far Wednesday's stored projection sits from the frozen snapshot, which says whether
week 1's post-hoc numbers can be trusted).

A snapshot is "pre-kickoff" for a player only if his NFL team had no stat row when it was taken.
A snapshot that fires late therefore cannot contaminate the accuracy data; it just covers fewer
players.

## 7. Data age and staleness

The page stores its build time. A script compares it with the clock on every view: amber past
16 hours, red with a banner past 26 hours. The job strip shows each job's last result from
`data/status.json`; a failed last run shows an amber banner even if the build itself is fresh.

## 8. What is deliberately not modeled yet

Matchup strength (opponent defense vs position), weather, Vegas totals, snap and target shares,
coordinator changes, and any calibration of the constants above. See the forecasting proposal in
the Fantasy-Football folder for what each would be worth and what it would cost.
