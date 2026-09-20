"""Builds the vacated-share Usage book from the nflverse cache, and the compact committed form
the offline dashboard build reads.

Three nflverse inputs, all already in data/history/ (see engine/history.py):
  stats_player_week_S.csv   targets, carries and the receiving / rushing stat lines
  injuries_S.csv            the weekly injury report: report_status and practice_status
  (play-by-play is NOT needed here; the 40-plus-yard touchdown bonus is the only offensive
   category it adds and it does not change a usage share)

Absence, decided the way a manager could have decided it on Sunday morning:
  a player is absent in week W if that week's injury report lists him Out or Doubtful, or if he
  was absent in week W-1 and had no stat row in W-1 (the carry-forward that covers players who
  drop off the report once they land on IR). He returns the moment he has a stat row again.
  Everything the rule reads is published before kickoff, so the historical replay stays honest.

Known gap, stated rather than filled: before 2016 the NFL required a status on every reported
player and from 2016 the status appears only for Out / Doubtful / Questionable. That makes the
"Out" set comparable across seasons but means a player who is inactive without ever appearing on
the report (a healthy scratch, a late suspension) is counted as available. The effect is to
understate vacated share, never to overstate it.
"""
import csv
from collections import defaultdict

from .. import history
from . import pbp, psl_scoring as ps
from .vacated import Usage

POS_GROUPS = ("QB", "RB", "WR", "TE")
REC_KEYS = ("rec", "rec_yd", "rec_td", "rec_2pt", "bonus_rec_yd_100", "bonus_rec_yd_200", "rec_td_40p")
RUSH_KEYS = ("rush_yd", "rush_td", "rush_2pt", "bonus_rush_yd_100", "bonus_rush_yd_200", "rush_td_40p")
OUT_STATUS = {"out", "doubtful"}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def split_points(row, scoring):
    """(receiving points, rushing points) for one nflverse weekly row under this league's scoring."""
    line = ps.offense_line(row, {})
    rec = sum(line.get(k, 0.0) * scoring.get(k, 0.0) for k in REC_KEYS)
    rush = sum(line.get(k, 0.0) * scoring.get(k, 0.0) for k in RUSH_KEYS)
    return round(rec, 3), round(rush, 3)


def load_rows(season, scoring, weeks_max=None, quiet=True):
    """Weekly usage rows and team totals for one season. Returns (rows, team_tot, played)."""
    path = history.fetch("stats", season, quiet=quiet)
    if not path:
        return None, None, None
    rows, team_tot, played = [], defaultdict(lambda: {"tgt": 0.0, "car": 0.0}), defaultdict(set)
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("season_type") != "REG":
                continue
            wk = int(r["week"])
            if weeks_max and wk > weeks_max:
                continue
            team = pbp.fix_team(r["team"])
            tgt, car = _f(r.get("targets")), _f(r.get("carries"))
            team_tot[(season, wk, team)]["tgt"] += tgt
            team_tot[(season, wk, team)]["car"] += car
            played[(season, wk, team)].add(r["player_id"])
            if r.get("position_group") not in POS_GROUPS:
                continue
            rec_pts, rush_pts = split_points(r, scoring)
            rows.append({"pid": r["player_id"], "name": r["player_display_name"], "pos": r["position_group"],
                         "team": team, "season": season, "week": wk, "tgt": tgt, "car": car,
                         "rec_pts": rec_pts, "rush_pts": rush_pts})
    return rows, dict(team_tot), played


def load_absent(season, played, weeks_max=None, quiet=True):
    """{(season, week, team): set(pid)} from the injury report plus the carry-forward rule."""
    path = history.fetch("injuries", season, quiet=quiet)
    if not path:
        return None
    reported = defaultdict(set)
    weeks = set()
    with open_text_or(path) as fh:
        for r in csv.DictReader(fh):
            if (r.get("game_type") or "REG") != "REG":
                continue
            wk_raw = r.get("week")
            if not wk_raw:
                continue
            wk = int(float(wk_raw))
            if weeks_max and wk > weeks_max:
                continue
            weeks.add(wk)
            pid = (r.get("gsis_id") or "").strip()
            if not pid:
                continue
            if (r.get("report_status") or "").strip().lower() in OUT_STATUS:
                reported[(season, wk, pbp.fix_team(r["team"]))].add(pid)
    out = {}
    for wk in sorted(weeks):
        teams = {t for (_, w, t) in list(reported) if w == wk} | {t for (_, w, t) in played if w == wk}
        for t in teams:
            carried = {p for p in out.get((season, wk - 1, t), set()) if p not in played.get((season, wk - 1, t), set())}
            out[(season, wk, t)] = reported.get((season, wk, t), set()) | carried
    return out


def open_text_or(path):
    return history.open_text(path)


def prior_tables(rows, team_tot, min_games=1):
    """Per-player previous-season shares and points per opportunity, plus team and league means."""
    by_pid = defaultdict(list)
    for r in rows:
        by_pid[r["pid"]].append(r)
    team_games = defaultdict(list)
    for (s, w, t), v in team_tot.items():
        team_games[t].append(v)
    prior_team = {t: {"tgt": sum(v["tgt"] for v in g) / len(g), "car": sum(v["car"] for v in g) / len(g)}
                  for t, g in team_games.items() if g}
    prior, pos_acc = {}, defaultdict(lambda: {"tgt": 0.0, "car": 0.0, "rec_pts": 0.0, "rush_pts": 0.0})
    for pid, gs in by_pid.items():
        if len(gs) < min_games:
            continue
        shares = {"tgt": [], "car": []}
        for g in gs:
            tt = team_tot.get((g["season"], g["week"], g["team"])) or {}
            for col in ("tgt", "car"):
                tot = tt.get(col) or 0.0
                shares[col].append((g.get(col) or 0.0) / tot if tot else 0.0)
        tgt = sum(g["tgt"] for g in gs)
        car = sum(g["car"] for g in gs)
        rec_pts = sum(g["rec_pts"] for g in gs)
        rush_pts = sum(g["rush_pts"] for g in gs)
        last = gs[-1]
        a = pos_acc[last["pos"]]
        a["tgt"] += tgt
        a["car"] += car
        a["rec_pts"] += rec_pts
        a["rush_pts"] += rush_pts
        prior[pid] = {"name": last["name"], "pos": last["pos"], "team": last["team"], "g": len(gs),
                      "tgt_share": round(sum(shares["tgt"]) / len(gs), 4),
                      "car_share": round(sum(shares["car"]) / len(gs), 4),
                      "ppt": round(rec_pts / tgt, 4) if tgt else None,
                      "ppc": round(rush_pts / car, 4) if car else None}
    prior_pos = {pos: {"ppt": round(a["rec_pts"] / a["tgt"], 4) if a["tgt"] else 0.0,
                       "ppc": round(a["rush_pts"] / a["car"], 4) if a["car"] else 0.0}
                 for pos, a in pos_acc.items()}
    return prior, prior_team, prior_pos


def build(season, scoring, weeks_max=None, history_seasons=1, quiet=True):
    """A Usage book for `season`, with priors from the season before and `history_seasons` extra
    completed seasons of rows behind it so the historical estimator has pairs to look at."""
    rows, team_tot, played = load_rows(season, scoring, weeks_max=weeks_max, quiet=quiet)
    if rows is None:
        return None
    absent = load_absent(season, played, weeks_max=weeks_max, quiet=quiet) or {}
    prev_rows, prev_tot, prev_played = load_rows(season - 1, scoring, quiet=quiet)
    prior, prior_team, prior_pos = ({}, {}, {})
    all_rows, all_tot = list(rows), dict(team_tot)
    if prev_rows:
        prior, prior_team, prior_pos = prior_tables(prev_rows, prev_tot)
        for s in range(season - history_seasons, season):
            r2, t2, p2 = (prev_rows, prev_tot, prev_played) if s == season - 1 else load_rows(s, scoring, quiet=quiet)
            if not r2:
                continue
            all_rows += r2
            all_tot.update(t2)
            absent.update(load_absent(s, p2, quiet=quiet) or {})
    return Usage(all_rows, all_tot, absent=absent, prior=prior, prior_team=prior_team,
                 prior_pos=prior_pos, season=season)


# ---------------------------------------------------------------- compact committed form
def to_compact(u, season, seasons_kept):
    """The small JSON the dashboard build reads with no network. Rows are rounded; the absence sets
    are stored as lists so the historical estimator still works offline."""
    return {
        "season": season, "seasons_in_rows": sorted(seasons_kept),
        "rows": [[r["pid"], r["name"], r["pos"], r["team"], r["season"], r["week"],
                  round(r["tgt"], 1), round(r["car"], 1), r["rec_pts"], r["rush_pts"]] for r in u.rows],
        "team_tot": {f"{s}|{w}|{t}": [round(v["tgt"], 1), round(v["car"], 1)] for (s, w, t), v in sorted(u.team_tot.items())},
        "absent": {f"{s}|{w}|{t}": sorted(v) for (s, w, t), v in sorted(u.absent.items()) if v},
        "prior": u.prior, "prior_team": {t: [round(v["tgt"], 2), round(v["car"], 2)] for t, v in sorted(u.prior_team.items())},
        "prior_pos": u.prior_pos,
    }


def from_compact(d):
    rows = [{"pid": a, "name": b, "pos": c, "team": t, "season": s, "week": w,
             "tgt": tg, "car": ca, "rec_pts": rp, "rush_pts": up}
            for a, b, c, t, s, w, tg, ca, rp, up in (d.get("rows") or [])]
    team_tot = {}
    for k, v in (d.get("team_tot") or {}).items():
        s, w, t = k.split("|")
        team_tot[(int(s), int(w), t)] = {"tgt": v[0], "car": v[1]}
    absent = {}
    for k, v in (d.get("absent") or {}).items():
        s, w, t = k.split("|")
        absent[(int(s), int(w), t)] = set(v)
    prior_team = {t: {"tgt": v[0], "car": v[1]} for t, v in (d.get("prior_team") or {}).items()}
    return Usage(rows, team_tot, absent=absent, prior=d.get("prior") or {}, prior_team=prior_team,
                 prior_pos=d.get("prior_pos") or {}, season=d.get("season"))
