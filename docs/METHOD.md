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
  is quoted as the tiebreak. The vacated target share column (section 10) is shown beside these
  rows but is not part of `expected` and does not change the tiebreak.

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

Player level, over three pools: every starter the 12 teams used that week (about 96), everyone
rostered (about 190), and the waiver pool, which is every player on nobody's roster whose Sleeper
projection for that week was 5.0 points or more (about 60 in week 1). Each pool gets MAE (average
absolute miss), bias (actual minus predicted) and Spearman rank correlation (does the ordering hold).

The waiver pool exists because the waiver engine recommends players nobody rosters and prices FAAB
bids off their projections, and until it was added none of those projections were ever graded. The
snapshots already freeze a projection for every projected player (about 3,150) and the weekly scored
file carries actual points for every cached player (about 840), so widening the scoring pool needed
no new collection. The 5.0 cut keeps out the several hundred players Sleeper projects near zero,
whose near-zero errors would flatter every baseline. Free agents are a different population from
starters (more part-time roles, more zeroes), so the waiver MAE is meant to be read against itself
week to week rather than against the starter MAE.

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

Matchup strength (opponent defense vs position), weather, Vegas totals, snap shares, coordinator
changes, and any calibration of the constants above. See the forecasting proposal in the
Fantasy-Football folder for what each would be worth and what it would cost.

Target and carry shares are now collected and displayed (section 10), but they are still not
modeled: they feed a display column only.

## 9. Historical backtest harness (offline, never scheduled)

`python engine.py histbacktest` replays ten seasons of public nflverse data (2015 to 2025) under
this league's scoring and answers the questions the in-season backtest (section 6, `backtest.py`)
will never have the sample size for. It runs beside the live pipeline, writes only
`data/derived/hist_backtest.json` and `.md` (shown on the dashboard's Backtest tab) and never
touches the Sleeper API or the files the scheduled jobs write. It is stdlib-only like the rest of
`engine/`; no separate `tools/` requirements were needed.

- **Data** (`engine/history.py`): nflverse weekly player stats and play-by-play per season, cached
  in `data/history/` (about 240 MB, gitignored) with a committed manifest of URL, timestamp, sha256,
  size, rows and columns. 2014 is loaded only as the prior for 2015; 2026 only for the scoring check.
- **Scoring** (`analysis/psl_scoring.py`, `analysis/pbp.py`): every one of the 88 settings is read
  from `league.json`. Offense comes from the weekly file plus play-by-play for 40-plus-yard TD
  bonuses and red-zone touches; defense comes entirely from play-by-play, including three-and-outs
  (drives that ended in a punt with no first down) and fourth-down stops. Gate: week 1 of 2026 must
  reproduce Sleeper's points within 0.1 for every offensive player before any model runs. It does,
  to the cent, for 357 players and all 32 defenses. Three facts learned from the gate: yardage
  bonuses are tiers, not stacks; DEF points allowed exclude the opponent's own defensive TDs; DEF
  tackles-for-loss are the sum of individual credits.
- **Point-in-time replay** (`analysis/histmodels.py`): a prediction for week N reads only weeks
  before N of that season plus completed prior seasons. A leakage test corrupts every week after
  week 9 with absurd values and asserts byte-identical predictions for weeks 2 to 9.
- **Selection discipline**: fit 2015 to 2019, select 2020 to 2024, report on held-out 2025 only,
  with a week-level paired bootstrap. 36 configurations tried.
- **Lineup metric**: a simulated 12-team league with this league's slots, fixed rosters drafted
  from prior-season points per game, each model setting each lineup each week, scored with real
  points against the hindsight-optimal lineup.
- **Findings** are in `Fantasy-Football/Backtest-Findings_v1.0_2026-09-18.md`. The headline: the
  engine's k=4 baseline half beats the plain season average by about 1.1 lineup points per
  team-week (interval excludes zero); nothing tried beats k=4 on lineup points with confidence; a
  rolling 3-week average is measurably worse; the one supported change is a half-strength opponent
  adjustment at DEF.
- **What it cannot do**: tune `w`, the weight on Sleeper's number, because no archive of Sleeper's
  weekly projections exists. It tunes only the baseline half that Sleeper is blended against.

## 10. Vacated target share (display only)

A column on the start/sit rows and the close-calls list saying how much of an absent teammate's
usage this player is likely to absorb, in points. **It is not part of `expected` and it does not
change the close-call tiebreak.** That constraint is not a style choice: the ten-season backtest
found opponent and role adjustments indistinguishable from zero on held-out data outside DEF, so
nothing new enters the projection until it has been measured on this league's own results. The
separate backtest below says the same thing about this signal in particular. `tests/test_vacated.py`
builds the real lineup twice, once with the column and once with it stubbed out, and asserts that
every expected number and the slot order are identical.

### What it computes

For each rostered WR, RB and TE, for the upcoming week:

1. **Vacated share.** Sum the prior usage share of every teammate at the same position who is Out,
   Doubtful, on IR or PUP, suspended, or carrying an inactive Sleeper roster status. Prior share is
   his recency-weighted (decay 0.1) season-to-date share of the team's targets, and of the team's
   carries for an RB, shrunk to his previous-season share with k = 4, the same shrinkage the
   baseline in section 2 uses.
2. **Expected absorption**, by one of two estimators:
   - *Proportional*: the vacated share is split among the remaining teammates at that position in
     proportion to their own prior shares.
   - *Historical*: for each absent teammate, the share this player actually took in past games where
     that teammate was out, minus his share in games where the teammate played, capped at what was
     actually vacated. Needs 3 games on each side; falls back to proportional otherwise.

   The 2015-2024 select block preferred *historical* by 0.02 lineup points a team-week, which is
   well inside the noise, so the choice between the two is effectively arbitrary. The live column
   uses historical (`ESTIMATOR` in `engine/analysis/vacated.py`).
3. **Points equivalent.** Absorbed share x the team's recency-weighted opportunities per game x the
   player's own shrunk points per target (or per carry), so the column reads in points like
   everything else on the row.

Position groups are narrow on purpose: a WR's vacated share counts absent WRs only. Targets vacated
by a TE do flow to WRs in reality; modelling that would need a cross-position absorption matrix the
backtest has no power to fit, so the narrow reading is used and stated. [Guessing] on the group
definition and on the three constants (decay 0.1, k = 4, 12 pseudo-opportunities on points per
opportunity); [Certain] that the column is display only.

### Where the data comes from

- **Usage**: nflverse weekly player stats, the same public source the historical harness uses.
  Sleeper publishes no target or carry counts, so a new collector, `python engine.py usage`,
  downloads the current and previous season's weekly file (about 0.6 MB) and writes
  `data/usage/<season>/usage.json`, which is committed. It runs inside the Wednesday pull, after
  every game of the previous week is final. `build` reads only that file, so the dashboard build
  stays a no-network job; if nflverse is unreachable the previous file stays in place and the column
  goes stale rather than wrong.
- **Absence, live**: the daily Sleeper injury tracker, which already records the injury and roster
  status of every fantasy-relevant player.
- **Absence, historical**: the nflverse `injuries` release, added to the fetch list in
  `engine/history.py`. It is present for every season from 2014 through 2026, so the backtest window
  did not have to be cut; `history.injuries_coverage()` reports it per season and the write-up prints
  the table. A player counts as absent in week W when that week's report says Out or Doubtful, or
  when he was absent in W-1 and had no stat row in W-1, which covers players who drop off the report
  once they land on IR. Everything that rule reads is published before kickoff. From 2016 the report
  only carries a status for Out, Doubtful and Questionable, so a healthy scratch who never appears on
  it is counted as available: that understates vacated share, it never overstates it.
- **Id mapping**: Sleeper ids to nflverse gsis ids, from Sleeper's own `gsis_id` field, then the
  preseason rankings file (which carries both), then a normalized name-and-team match. In week 2 of
  2026, 651 ids mapped and none of the roster was left unmatched.

### What the backtest found

Full tables in `data/derived/hist_backtest.md` and on the dashboard's Backtest tab; the command is
`python engine.py vacatedbacktest` (a full `histbacktest` also runs it). Seasons 2015 to 2024
selected the estimator; 2025 was held out and touched once. Three arms, all starting from the same
lineup chosen by expected points and allowed to swap only inside the same 1.5-point close-call
window: no tiebreak, the current boom-rate tiebreak, and the vacated tiebreak.

**Null result.** On held-out 2025 the vacated tiebreak did not beat the boom-rate tiebreak: -0.19
lineup points per team-week, 95% interval -0.89 to +0.55, over 17 weeks. Against no tiebreak at all
it was -0.23 (-0.42 to -0.06), i.e. measurably worse: swapping starters on this signal inside the
close-call window costs points. The column therefore ships as information only and the tiebreak
stays on boom rate. For scale, the boom-rate rule itself was -0.04 (-0.70 to +0.58) against no
tiebreak on 2025 and -0.42 (-0.71 to -0.14) on the select block, so nothing here promotes it either;
whether that rule earns its place is its own question, not this one.

The column is still worth showing. It is the only place on the page that says, in points, what a
teammate's absence is worth, and the week-2 Sutton-over-Boston miss recorded in the project status is
exactly the kind of role change it makes visible.

### Limits, stated rather than buried

- The backtest replays the engine's k = 4 baseline half, not the live 0.65 Sleeper blend. No archive
  of Sleeper's weekly projections exists, so the live blend cannot be replayed at all.
- Boom rate in the backtest is computed from the previous season. The preseason model's `boom_rate`
  column is a 2026 artifact with no historical equivalent.
- Rosters in the simulation are drafted from prior-season points per game and held fixed; no waivers,
  no trades.
- A player with no nflverse id match gets no column rather than a zero, and the page says how many.

## 11. League FAAB market and the league bid

Added 2026-10 after the week 4 review: the engine bid priced claims off national Sleeper add counts,
not off how this league bids.

**Market history** (`engine/analysis/market.py`, Waivers tab). Sleeper's transaction log keeps every
waiver claim including the failed ones, with its bid, so for every player claimed in a waiver run the
page shows the winner, the winning bid, every losing bid and the number of bidders. A waiver run is
every claim processed in the same minute; the log's week key is not used because Sleeper files a claim
under the week it was made, not the week it ran. A failed claim can fail for reasons other than being
outbid (roster full after an earlier claim, budget, a tie lost on priority). Sleeper writes the reason
into `metadata.notes`, which the pull keeps from October 2026 on; before that, a losing bid above the
winning bid is labelled "failed for another reason" rather than read as an outbid. [Certain] on the
data, [Likely] on the reading of the pre-October failures.

From the log: a per-position price guide (median and max winning bid, overall and when 2 or more teams
bid), the median winning bid of each run's single most-contested player, and per team the FAAB spent
(checked against Sleeper's `waiver_budget_used`), left, claims, biggest win and the amounts it repeats
(Derrelick won twice at exactly $31). Player ids resolve through `data/players/names_cache.json`, which
the pull and the daily injury job extend with every id that has ever appeared in a transaction and
never prune, so a player cut from the league keeps his name.

**League bid** (`engine/analysis/bidding.py`), shown beside the engine bid, which is unchanged:

    value_cap  = gain x weeks_left x $0.60, capped at 45% of budget left (60% at a 5+ point gain)
    market     = 3+ likely bidders: median winning bid of each run's most-contested player
                 2: median contested winning bid at the position;  0-1: median winning bid at the position
    pace       = 1, or with faab_leftover_tendency on:
                 clamp((budget_left / budget_total) / (weeks_left / season_weeks), 1.0, 1.5)
    league_bid = pace x min(value_cap, max(market, 1))
    to_beat    = $2 over the highest known amount among the likely bidders (an amount the team has bid
                 two or more times, or its highest bid at this position); red when above value_cap x pace

Each claim quotes a comparable: the newest weekly run's top add at the position (a run with four or
more claimed players; a two-claim Saturday trickle is not a market). [Guessing] on the bidder tiers,
the 1.5 pace cap and the $2 margin; the sample is about twenty completed claims after three runs.

`faab_leftover_tendency` (config/preferences.json) exists because Aaron usually finishes a season with
FAAB unspent. With $200 left and 14 of 17 weeks to go the pace factor is x1.21, and the page also
states the leftover projected at his season-to-date spending rate.

## 12. Likely bidders (competitor threat)

`engine/analysis/threats.py` scores every other team with FAAB left for each claim, and lists the top
three with the reasons in words: +4 owns an absent player at the target's position on the same NFL team
(Amateur Hour owns De'Von Achane, so they are the natural Ollie Gordon bidder), +1.5 owns a Questionable
one, +1 owns the healthy number 1 there (handcuff interest), +2 / +1 an Out or IR / Questionable starter
at the position, +2 a starter there ruled out or put on IR in the last 7 days (from the daily injury
diffs, when not already counted), +1 dropped a player at the position in the last 7 days, +1 a starter
there on bye next week, +1 healthy players at the position no more than the starting slots (not for
DEF, where everyone carries one), +0.5 has bid on the position this season. [Guessing] on every weight;
they only order the list and set the bidder count for the market tier above.

## 13. Ceiling and speculative claims (RB and WR)

The engine ranks claims by expected points, so a player whose role just changed can miss the list
(Ollie Gordon, week 4, with Achane on IR). `engine/analysis/opportunity.py` adds, from the vacated-share
signal of section 10:

    bump_now      points a week he absorbs from teammates at his position who are absent now
    bump_if_lead  the same with the healthy teammate ahead of him (more usage) also absent
    ceiling       ros + max(bump_now, bump_if_lead)

A waiver player is a **speculative claim** when the ceiling gap is 4.0 points a week or more, or when
his gain at the ceiling would be 3.0 or more while his normal gain earns no bid. Speculative claims whose
role is open now (bump_now of 3.0 or more) are listed first. The speculative bid is
min(5% of budget left, ceiling gain x weeks left x $0.60 x 0.25), at least $1, and never above the
league bid. [Guessing] on all of it.

**Conflict with section 10, stated rather than buried:** section 10 keeps the vacated signal display
only, because the ten-season backtest found it null as a start/sit tiebreak. It is still display only
for `expected`, `ros`, the waiver gain and the engine bid (`tests/test_opportunity.py` asserts it). The
speculative bid is the one place it sizes money, it is small and capped, and it has never been
backtested as a waiver signal. The calls scorecard (section 16) grades it from week 5 on.

## 14. Drop list and handcuffs

Every droppable player shows why he is on the list: his rest-of-season value and rank, whether he
starts in this week's recommended lineup, his injury tag, and a handcuff note. A handcuff is an RB whose
same-team teammate has more usage and who would gain 3 or more points a week if that teammate missed
time (Rico Dowdle, PIT backup to Jaylen Warren). Rule: an injured handcuff is never picked as the
automatic drop for a claim while a healthy, lower-value non-handcuff is droppable. [Guessing] on the
threshold.

## 15. Head-to-head card

Lineup tab. The opponent comes from the week's matchup file. Both sides are valued with the same blend
(section 2): the opponent's set lineup and the best lineup his roster allows. A player with no
projection row in the committed data at all (other teams' players before Thursday's first pre-kickoff
snapshot; from October the pull stores every rostered player's projection) is valued at his baseline
and marked. Favored when Aaron's recommended total leads by more than 5 points, underdog when it trails
by more than 5, otherwise a toss-up [Guessing]. Because of the median game, Aaron's total is also
compared with the median of the other teams' set lineups. The lineup logic stays max expected points.

## 16. Calls scorecard

Accuracy tab, separate from projection accuracy: it grades decisions. Every build records the
upcoming week's calls in `data/derived/calls/<season>/weekNN.json`: the recommended lineup, every
change and close call, the claims, DEF streams and speculative claims, and the structured calls the
news synthesis writes into `data/synthesis/latest.json`. A start/sit row freezes once either player
kicks off; claims freeze at the Thursday 2 AM waiver run. Weeks 2 to 4 were reconstructed from git
history (`tools/backfill_calls.py`), and the synthesis calls for those weeks were extracted by hand.

Once `weekNN_scored.json` exists: a start/sit call is a hit when the player recommended to start scored
at least as much as the alternative; a DEF stream when the claimed defense outscored the one it would
have replaced that week; a claim when the added player outscored the player he would have replaced,
summed over every completed week since. "Followed" is what Aaron actually did, from the matchup file
(his starters) and the transaction log (his bids). A call made after one of its players kicked off is
not graded. Running hit rate by call type and source.
