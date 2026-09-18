"""Season tables for the historical harness, and the scoring gate.

For each season this builds, from the nflverse weekly file plus the play-by-play reduction:
  players   list of player-week dicts for QB/RB/WR/TE (regular season, weeks with a stat row):
            pid, name, pos, team, opp, week, pts (PSL points), targets, carries, rec, rec_yd, rush_yd,
            touches, yards, tds, rz (red-zone touches), tgt_share, ay_share (nflverse), car_share
  defense   list of team-week dicts: team, opp, week, pts (PSL DEF points), line (Sleeper keys)
  team_tot  {(week, team): {"targets": .., "carries": .., "rz": ..}}

The gate (B2): reproduce Sleeper's real week-1 2026 PSL points from this pipeline. Offense must
agree within 0.1 for every matched player; DEF is reported separately with its own tolerance.
"""
import csv
import json
import os
import re
from collections import defaultdict

from .. import config, store
from ..history import hist_dir, fetch
from . import pbp, psl_scoring as ps

POS_GROUPS = ("QB", "RB", "WR", "TE")
SLEEPER_TEAM = {"LA": "LAR"}           # nflverse code -> Sleeper code


def scoring_from_league(data_dir=None):
    league = store.read_json(os.path.join(data_dir or config.DATA_DIR, "league", "league.json"), {}) or {}
    sc = {k: float(v) for k, v in (league.get("scoring_settings") or {}).items()}
    if len(sc) < 80:
        raise RuntimeError(f"league.json has {len(sc)} scoring settings; expected the full 88")
    slots = [p for p in (league.get("roster_positions") or []) if p not in ("BN", "IR")]
    return sc, slots, league


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load_season(season, scoring, weeks_max=None, quiet=True):
    """Return {"season", "players", "defense", "team_tot", "weeks"} or None if files are missing."""
    stats_path = fetch("stats", season, quiet=quiet)
    if not stats_path:
        return None
    red = pbp.load_season(season)
    if red is None:
        return None
    players, team_tot = [], defaultdict(lambda: {"targets": 0.0, "carries": 0.0, "rz": 0.0, "tfl": 0.0})
    with open(stats_path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("season_type") != "REG":
                continue
            wk = int(r["week"])
            if weeks_max and wk > weeks_max:
                continue
            team = pbp.fix_team(r["team"])
            tt = team_tot[(wk, team)]
            tt["tfl"] += _f(r.get("def_tackles_for_loss"))
            pg = r.get("position_group")
            if pg not in POS_GROUPS:
                continue
            ex = red["players"].get(f"{wk}|{r['player_id']}", {})
            pts = ps.score_offense(r, ex, scoring)
            tg, ca, rc = _f(r.get("targets")), _f(r.get("carries")), _f(r.get("receptions"))
            rz = _f(ex.get("rz_touches"))
            tt["targets"] += tg
            tt["carries"] += ca
            tt["rz"] += rz
            players.append({
                "pid": r["player_id"], "name": r["player_display_name"], "pos": pg, "team": team,
                "opp": pbp.fix_team(r.get("opponent_team") or ""), "week": wk, "pts": pts,
                "targets": tg, "carries": ca, "rec": rc, "rec_yd": _f(r.get("receiving_yards")),
                "rush_yd": _f(r.get("rushing_yards")), "pass_att": _f(r.get("attempts")),
                "touches": ca + rc, "yards": _f(r.get("receiving_yards")) + _f(r.get("rushing_yards")),
                "tds": _f(r.get("rushing_tds")) + _f(r.get("receiving_tds")) + _f(r.get("passing_tds")),
                "rz": rz, "tgt_share": _f(r.get("target_share")), "ay_share": _f(r.get("air_yards_share")),
                "air_yards": _f(r.get("receiving_air_yards")),
            })
    for p in players:
        tt = team_tot[(p["week"], p["team"])]
        p["car_share"] = round(p["carries"] / tt["carries"], 4) if tt["carries"] else 0.0
        p["tgt_share_calc"] = round(p["targets"] / tt["targets"], 4) if tt["targets"] else 0.0
        p["rz_share"] = round(p["rz"] / tt["rz"], 4) if tt["rz"] else 0.0
    defense = []
    for key, line in red["teams"].items():
        wk_s, team = key.split("|")
        wk = int(wk_s)
        if weeks_max and wk > weeks_max:
            continue
        line = dict(line)
        line["tkl_loss"] = team_tot[(wk, team)]["tfl"]       # Sleeper's team TFL = sum of player TFL credits
        defense.append({"team": team, "opp": line.get("opp"), "week": wk, "pts": ps.score_defense(line, scoring), "line": line})
    weeks = sorted({p["week"] for p in players})
    return {"season": season, "players": players, "defense": defense,
            "team_tot": {f"{w}|{t}": v for (w, t), v in team_tot.items()}, "weeks": weeks}


def _norm(n):
    return re.sub(r"[^a-z]", "", re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", (n or "").lower()))


def gate(data_dir=None, tol=0.1):
    """Compare the reconstruction with Sleeper's real week-1 2026 points. Returns a report dict."""
    d = data_dir or config.DATA_DIR
    scoring, _, _ = scoring_from_league(d)
    season = load_season(2026, scoring, weeks_max=1)
    if not season:
        return {"ok": False, "reason": "2026 nflverse files unavailable"}
    scored = store.read_json(os.path.join(d, "weeks", "2026", "week01_scored.json"), {}) or {}
    sl = scored.get("players") or {}
    ui_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(d))), "..", "..", "Fantasy-Football", "week1_fantasy_scores.csv")
    by_key, by_last, by_name = {}, defaultdict(list), defaultdict(list)
    for p in season["players"]:
        if p["week"] != 1:
            continue
        tm = SLEEPER_TEAM.get(p["team"], p["team"])
        by_key[(_norm(p["name"]), tm)] = p
        by_last[(_norm(p["name"].split()[-1]), tm, p["pos"])].append(p)
        by_name[_norm(p["name"])].append(p)
    matched_pids = set()
    rows, mism, unmatched = [], [], []
    for pid, s in sl.items():
        if s.get("pos") == "DEF" or s.get("actual") is None:
            continue
        k = (_norm(s["name"]), s["team"])
        hit = by_key.get(k)
        if hit:
            matched_pids.add(hit["pid"])
    for pid, s in sl.items():
        if s.get("pos") == "DEF" or s.get("actual") is None:
            continue
        k = (_norm(s["name"]), s["team"])
        hit = by_key.get(k)
        how = "name+team"
        if not hit:
            c = [x for x in by_last.get((_norm(s["name"].split()[-1]), s["team"], s["pos"]), []) if x["pid"] not in matched_pids]
            if len(c) == 1:
                hit, how = c[0], "last name+team+pos"
        if not hit:
            c = [x for x in by_name.get(_norm(s["name"]), []) if x["pid"] not in matched_pids and x["pos"] == s["pos"]]
            if len(c) == 1:
                hit, how = c[0], "name only (team differs)"
        if not hit:
            if s["actual"] != 0:
                unmatched.append({"name": s["name"], "team": s["team"], "pos": s["pos"], "sleeper": s["actual"]})
            continue
        matched_pids.add(hit["pid"])
        diff = round(hit["pts"] - s["actual"], 2)
        rows.append({"name": s["name"], "team": s["team"], "pos": s["pos"], "sleeper": s["actual"], "ours": hit["pts"], "diff": diff, "match": how})
        if abs(diff) > tol:
            mism.append(rows[-1])
    # DEF
    def_rows, def_mism = [], []
    for pid, s in sl.items():
        if s.get("pos") != "DEF" or s.get("actual") is None:
            continue
        tm = {"LAR": "LA"}.get(s["team"], s["team"])
        mine = next((x for x in season["defense"] if x["week"] == 1 and x["team"] == tm), None)
        if not mine:
            def_mism.append({"team": s["team"], "sleeper": s["actual"], "ours": None, "diff": None})
            continue
        diff = round(mine["pts"] - s["actual"], 2)
        sd = s.get("def_stats") or {}
        cat = {k: [sd.get(k), mine["line"].get(k, 0)] for k in set(sd) | set(mine["line"]) if k not in ("opp", "yds_allow") and (sd.get(k) or 0) != mine["line"].get(k, 0)}
        def_rows.append({"team": s["team"], "sleeper": s["actual"], "ours": mine["pts"], "diff": diff, "category_diffs": cat})
        if abs(diff) > tol:
            def_mism.append(def_rows[-1])
    by_pos = defaultdict(lambda: {"n": 0, "max_abs": 0.0, "mism": 0})
    for r in rows:
        b = by_pos[r["pos"]]
        b["n"] += 1
        b["max_abs"] = max(b["max_abs"], abs(r["diff"]))
        b["mism"] += 1 if abs(r["diff"]) > tol else 0
    ok = not mism
    return {"ok": ok, "tolerance": tol, "n_compared": len(rows), "n_mismatch": len(mism), "mismatches": mism,
            "unmatched_nonzero": unmatched, "by_pos": dict(by_pos),
            "def": {"n": len(def_rows), "n_mismatch": len(def_mism), "max_abs": max((abs(r["diff"]) for r in def_rows if r["diff"] is not None), default=None),
                    "mismatches": def_mism, "rows": def_rows},
            "note": ("Offensive players matched to nflverse by normalized name and team (fallback: last name + team + position, "
                     "then name only when unique). Sleeper players with 0.0 actual and no nflverse row are consistent by construction "
                     "and are not counted.")}
