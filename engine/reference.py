"""Loaders for the preseason reference files copied into reference/ (rankings v2.0, DEF rankings,
2026 schedule). Read-only. The originals live in Aaron's Fantasy-Football folder."""
import csv
import os

from . import config

_cache = {}


def _path(name):
    return os.path.join(config.REFERENCE_DIR, name)


def _num(v):
    if v is None or v == "" or v == "NOT_AVAILABLE":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def rankings():
    """dict sleeper_id -> row (numbers parsed). Players without a sleeper_id are keyed by name."""
    if "rank" in _cache:
        return _cache["rank"]
    out = {}
    path = _path(config.RANKINGS_CSV)
    if not os.path.exists(path):
        _cache["rank"] = out
        return out
    num_cols = {"suggested_rank", "pos_rank", "depth_chart_order", "proj_ppg", "exp_games", "proj_season_pts",
                "replacement_pts", "vor", "vor_ceiling_tilt", "rank_ceiling_tilt", "n_eff", "wtd_ppg",
                "ppg_2025", "ppg_2024", "ppg_2023", "g_2025", "sd_wk", "cv", "p85_wk", "boom_rate",
                "startable_rate", "bust_rate", "ceiling_z", "years_exp", "draft_number", "age"}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            r = dict(row)
            for c in num_cols:
                if c in r:
                    r[c] = _num(r[c])
            sid = (row.get("sleeper_id") or "").strip()
            if sid.endswith(".0"):
                sid = sid[:-2]
            r["sleeper_id"] = sid
            key = sid or ("name:" + row.get("player_name", ""))
            out[key] = r
    _cache["rank"] = out
    return out


def rankings_by_name():
    return {r.get("player_name", "").lower(): r for r in rankings().values()}


def def_rankings():
    """dict team -> row."""
    if "def" in _cache:
        return _cache["def"]
    out = {}
    path = _path(config.DEF_RANKINGS_CSV)
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                r = {k: (_num(v) if k not in ("team",) else v) for k, v in row.items()}
                out[row["team"]] = r
    _cache["def"] = out
    return out


def schedule():
    """dict (team, week) -> {opponent, is_home, gameday, bye}."""
    if "sched" in _cache:
        return _cache["sched"]
    out = {}
    path = _path(config.SCHEDULE_CSV)
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    wk = int(row["week"])
                except (KeyError, ValueError):
                    continue
                out[(row["team"], wk)] = {"opponent": row.get("opponent"),
                                          "is_home": str(row.get("is_home")).lower() == "true",
                                          "gameday": row.get("gameday"),
                                          "bye": str(row.get("bye")).lower() == "true" or row.get("opponent") == "BYE"}
    _cache["sched"] = out
    return out


def bye_week(team):
    for (t, wk), v in schedule().items():
        if t == team and v["bye"]:
            return wk
    return None


def preseason_ppg(pid, pos, team):
    """Preseason expectation for one player: proj_ppg from rankings, or wtd_def_ppg for a DEF."""
    if pos == "DEF":
        d = def_rankings().get(team or pid)
        return d.get("wtd_def_ppg") if d else None
    r = rankings().get(pid)
    return r.get("proj_ppg") if r else None


def preseason_row(pid, pos, team):
    if pos == "DEF":
        return def_rankings().get(team or pid)
    return rankings().get(pid)
