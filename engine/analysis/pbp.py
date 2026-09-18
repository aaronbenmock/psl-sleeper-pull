"""Play-by-play reduction for the historical harness (stdlib only).

nflverse weekly player stats carry every offensive category this league scores except three:
40-plus-yard touchdown bonuses, kick/punt return touchdowns split by type, and red-zone touches.
Team defense needs play-by-play for everything Sleeper scores at the unit level, in particular the
two categories this league pays for that no projection or weekly file carries: three-and-outs
(def_3_and_out, 0.5) and fourth-down stops (def_4_and_stop, 1.0).

One pass over play_by_play_S.csv.gz produces, per season:
  teams[(week, team)]   Sleeper-keyed defense stat line (sack, int, fum_rec, ff, def_td, def_st_td,
                        def_st_ff, def_st_fum_rec, safe, blk_kick, tkl_loss, pts_allow, yds_allow,
                        def_3_and_out, def_4_and_stop, def_2pt) plus opponent
  players[(week, gsis)] extras: pass_td_40p, rush_td_40p, rec_td_40p, kr_td, pr_td, rz_carries,
                        rz_targets, rz_touches
  team_rz[(week, team)] red-zone carries and targets for the offense (denominator for shares)

Definitions (stated so they can be checked against Sleeper's week-1 2026 numbers; the gate does that):
  three-and-out   a drive (fixed_drive) whose result is a punt and that recorded no first down
  fourth-down stop a play flagged fourth_down_failed (the offense turned it over on downs)
  pts_allow       the opponent's final score minus 6 for each touchdown the opponent's defense or
                  special teams scored (Sleeper does not charge a DEF for a pick-six thrown by its own
                  offense; ATL, CIN and TB in week 1 2026 all sat exactly 6 below the final score)
  tkl_loss        NOT from play-by-play: Sleeper's team total equals the sum of the per-player
                  def_tackles_for_loss in the weekly stats file (32 of 32 matched), so the loader
                  overrides it from there
  def_td          a touchdown scored by the team that did not have possession on a scrimmage play
  def_st_td       a kickoff or punt return touchdown, or a blocked-kick return touchdown
Regular season only. Old franchise codes are mapped to the current ones so a defense keeps one
identity across seasons (SD to LAC, STL to LA, OAK to LV).

The result is cached at data/history/derived/pbp_S.json (gitignored, rebuilt from the raw file).
"""
import csv
import os
from collections import defaultdict

from .. import store
from ..history import open_text, hist_dir

TEAM_FIX = {"SD": "LAC", "STL": "LA", "OAK": "LV", "JAC": "JAX"}


def fix_team(t):
    return TEAM_FIX.get(t, t)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _i(v):
    return int(_f(v))


def reduce_season(path):
    """Read one season's play-by-play and return the reduced tables (plain dicts, JSON-safe)."""
    teams = defaultdict(lambda: defaultdict(float))
    players = defaultdict(lambda: defaultdict(float))
    team_rz = defaultdict(lambda: defaultdict(float))
    drives = {}              # (game, fixed_drive) -> (week, posteam, defteam, result, first_downs)
    finals = {}              # game -> (week, home, away, home_score, away_score)
    with open_text(path) as fh:
        r = csv.reader(fh)
        hdr = next(r)
        ix = {h: i for i, h in enumerate(hdr)}
        need = ["game_id", "week", "season_type", "posteam", "defteam", "home_team", "away_team", "home_score", "away_score",
                "fixed_drive", "fixed_drive_result", "drive_first_downs", "fourth_down_failed", "sack", "interception",
                "fumble", "fumble_lost", "fumble_forced", "fumble_recovery_1_team", "touchdown", "td_team", "return_touchdown",
                "safety", "punt_blocked", "field_goal_result", "extra_point_result", "defensive_two_point_conv",
                "tackled_for_loss", "play_type", "yards_gained", "pass_touchdown", "rush_touchdown", "passer_player_id",
                "rusher_player_id", "receiver_player_id", "td_player_id", "yardline_100", "pass_attempt", "rush_attempt",
                "kickoff_attempt", "punt_attempt", "special_teams_play", "qb_kneel", "two_point_conv_result",
                "lateral_rusher_player_id", "lateral_receiver_player_id", "fumbled_1_team", "own_kickoff_recovery"]
        missing = [n for n in need if n not in ix]
        if missing:
            raise ValueError(f"{os.path.basename(path)} lacks columns {missing}")
        g = lambda row, k: row[ix[k]]  # noqa: E731
        for row in r:
            if g(row, "season_type") != "REG":
                continue
            wk = _i(g(row, "week"))
            game = g(row, "game_id")
            home, away = fix_team(g(row, "home_team")), fix_team(g(row, "away_team"))
            finals[game] = (wk, home, away, _i(g(row, "home_score")), _i(g(row, "away_score")))
            pos, deft = fix_team(g(row, "posteam")), fix_team(g(row, "defteam"))
            ptype = g(row, "play_type")
            fd = g(row, "fixed_drive")
            if fd and pos:
                drives[(game, fd)] = (wk, pos, deft, g(row, "fixed_drive_result"), _i(g(row, "drive_first_downs")))
            if not pos or not deft:
                continue
            st_play = _i(g(row, "special_teams_play")) == 1 or ptype in ("kickoff", "punt", "field_goal", "extra_point")
            D = teams[(wk, deft)]
            O = teams[(wk, pos)]
            D["opp"] = pos
            O["opp"] = deft
            D["_seen"] = 1
            O["_seen"] = 1
            if not st_play:
                D["yds_allow"] += _f(g(row, "yards_gained")) if ptype in ("pass", "run", "qb_kneel", "qb_spike") else 0
            if _i(g(row, "fourth_down_failed")) == 1:
                D["def_4_and_stop"] += 1
            if _i(g(row, "sack")) == 1:
                D["sack"] += 1
            if _i(g(row, "interception")) == 1:
                D["int"] += 1
            if _i(g(row, "tackled_for_loss")) == 1:
                D["tkl_loss"] += 1
            if _i(g(row, "safety")) == 1:
                D["safe"] += 1
            if _i(g(row, "defensive_two_point_conv")) == 1:
                D["def_2pt"] += 1
            if _i(g(row, "punt_blocked")) == 1 or g(row, "field_goal_result") == "blocked" or g(row, "extra_point_result") == "blocked":
                D["blk_kick"] += 1
            if _i(g(row, "fumble_forced")) == 1:
                fumbled = fix_team(g(row, "fumbled_1_team")) or pos
                forcer = deft if fumbled == pos else pos
                teams[(wk, forcer)]["def_st_ff" if st_play else "ff"] += 1
            if _i(g(row, "fumble")) == 1 and _i(g(row, "fumble_lost")) == 1:
                rec_team = fix_team(g(row, "fumble_recovery_1_team"))
                fumbled = fix_team(g(row, "fumbled_1_team")) or pos
                if rec_team and rec_team != fumbled:
                    teams[(wk, rec_team)]["def_st_fum_rec" if st_play else "fum_rec"] += 1
            if _i(g(row, "touchdown")) == 1:
                tdt = fix_team(g(row, "td_team"))
                yg = _f(g(row, "yards_gained"))
                if _i(g(row, "return_touchdown")) == 1 and ptype in ("kickoff", "punt"):
                    teams[(wk, tdt)]["def_st_td"] += 1
                    key = "kr_td" if ptype == "kickoff" else "pr_td"
                    pid = g(row, "td_player_id")
                    if pid:
                        players[(wk, pid)][key] += 1
                elif tdt and tdt != pos:
                    teams[(wk, tdt)]["def_st_td" if st_play else "def_td"] += 1
                else:
                    if _i(g(row, "pass_touchdown")) == 1 and yg >= 40:
                        if g(row, "passer_player_id"):
                            players[(wk, g(row, "passer_player_id"))]["pass_td_40p"] += 1
                        rcv = g(row, "lateral_receiver_player_id") or g(row, "receiver_player_id")
                        if rcv:
                            players[(wk, rcv)]["rec_td_40p"] += 1
                    elif _i(g(row, "rush_touchdown")) == 1 and yg >= 40:
                        rsh = g(row, "lateral_rusher_player_id") or g(row, "rusher_player_id")
                        if rsh:
                            players[(wk, rsh)]["rush_td_40p"] += 1
            # red zone touches (offense inside the opponent 20)
            y100 = _f(g(row, "yardline_100"))
            if y100 and y100 <= 20 and not st_play:
                if _i(g(row, "rush_attempt")) == 1 and _i(g(row, "qb_kneel")) != 1 and g(row, "rusher_player_id"):
                    players[(wk, g(row, "rusher_player_id"))]["rz_carries"] += 1
                    team_rz[(wk, pos)]["rz_carries"] += 1
                if _i(g(row, "pass_attempt")) == 1 and g(row, "receiver_player_id"):
                    players[(wk, g(row, "receiver_player_id"))]["rz_targets"] += 1
                    team_rz[(wk, pos)]["rz_targets"] += 1
    # drives -> three-and-outs
    for (game, fd), (wk, pos, deft, res, fdn) in drives.items():
        if res == "Punt" and fdn == 0 and deft:
            teams[(wk, deft)]["def_3_and_out"] += 1
    # points allowed = opponent final score minus the opponent's own defensive / special-teams touchdowns
    for game, (wk, home, away, hs, as_) in finals.items():
        away_dtd = teams[(wk, away)].get("def_td", 0) + teams[(wk, away)].get("def_st_td", 0)
        home_dtd = teams[(wk, home)].get("def_td", 0) + teams[(wk, home)].get("def_st_td", 0)
        teams[(wk, home)]["pts_allow"] = as_ - 6 * away_dtd
        teams[(wk, away)]["pts_allow"] = hs - 6 * home_dtd
        teams[(wk, home)]["opp"] = away
        teams[(wk, away)]["opp"] = home
    out_t = {}
    for (wk, t), d in teams.items():
        if not d.get("_seen"):
            continue
        row = {k: (v if k == "opp" else round(v, 2)) for k, v in d.items() if not k.startswith("_")}
        out_t[f"{wk}|{t}"] = row
    out_p = {f"{wk}|{pid}": dict(d) for (wk, pid), d in players.items()}
    for d in out_p.values():
        d["rz_touches"] = d.get("rz_carries", 0) + d.get("rz_targets", 0)
    out_rz = {f"{wk}|{t}": dict(d) for (wk, t), d in team_rz.items()}
    return {"teams": out_t, "players": out_p, "team_rz": out_rz, "n_games": len(finals)}


def load_season(season, path=None, force=False):
    cache = os.path.join(hist_dir(), "derived", f"pbp_{season}.json")
    if not force:
        c = store.read_json(cache, None)
        if c:
            return c
    path = path or os.path.join(hist_dir(), f"play_by_play_{season}.csv.gz")
    if not os.path.exists(path):
        return None
    red = reduce_season(path)
    red["season"] = season
    store.write_json(cache, red, compact=True)
    return red
