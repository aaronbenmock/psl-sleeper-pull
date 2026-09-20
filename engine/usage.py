"""Weekly usage collector: the only new data the vacated-share column needs.

Sleeper publishes no target or carry counts, so the shares come from nflverse, the same public
source the historical harness already uses. This job downloads two small files per season into
data/history/ (the current season's weekly stats and injury report, about 0.6 MB together, plus
the previous season's for the priors and the historical estimator) and writes one compact,
committed file:

    data/usage/<season>/usage.json

Everything downstream, including `build`, reads only that file, so the dashboard build stays a
no-network job. When nflverse is unreachable the previous file is left in place and the column
simply goes stale; the file records when it was written and the dashboard says so.

Runs inside the Wednesday pull (after every game of the previous week is final) and can be run on
its own with `python engine.py usage`.
"""
import os
import re

from . import config, store, history
from .analysis import histdata, usagedata
from .sleeper import load_cached_players_only
from .timeutil import now_utc, iso

KEEP_POS = ("WR", "RB", "TE")


def _norm(n):
    return re.sub(r"[^a-z]", "", re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", (n or "").lower()))


def id_map(data_dir, u):
    """Sleeper player_id -> nflverse gsis id. Three sources, most reliable first: the gsis_id field
    in Sleeper's own player record, the preseason rankings file (which carries both ids), then a
    normalized name + team match against this season's usage rows."""
    from . import reference
    out, how = {}, {"gsis_field": 0, "rankings": 0, "name_team": 0}
    players, _ = load_cached_players_only(data_dir)
    for pid, p in players.items():
        g = p.get("gsis_id")
        if g:
            out[pid] = g
            how["gsis_field"] += 1
    for row in reference.rankings().values():
        sid, g = row.get("sleeper_id"), (row.get("player_id") or "").strip()
        if sid and g and g.startswith("00-") and sid not in out:
            out[sid] = g
            how["rankings"] += 1
    by_name_team, by_name = {}, {}
    for pid in u.games:
        key = (_norm(u.name_of.get(pid)), u.team_of.get(pid))
        by_name_team[key] = pid
        by_name.setdefault(_norm(u.name_of.get(pid)), []).append(pid)
    for pid, p in players.items():
        if pid in out or p.get("position") not in KEEP_POS:
            continue
        n = _norm(p.get("full_name"))
        g = by_name_team.get((n, p.get("team")))
        if not g:
            c = by_name.get(n) or []
            g = c[0] if len(c) == 1 else None
        if g:
            out[pid] = g
            how["name_team"] += 1
    return out, how


def run(out_dir=None, season=None):
    data_dir = out_dir or config.DATA_DIR
    started = iso(now_utc())
    scoring, _, _ = histdata.scoring_from_league(data_dir)
    season = int(season or (store.read_json(os.path.join(data_dir, "latest.json"), {}) or {}).get("meta", {}).get("season")
                 or config.SEASON_HINT)
    got = {k: history.fetch(k, season, force=True, quiet=True) for k in ("stats", "injuries")}
    for k in ("stats", "injuries"):
        history.fetch(k, season - 1, quiet=True)
    if not got["stats"]:
        summary = f"nflverse stats for {season} unavailable; kept the committed usage file"
        store.record_run("usage", False, summary, started, iso(now_utc()))
        print("usage:", summary)
        return None
    u = usagedata.build(season, scoring, quiet=True)
    if u is None:
        summary = f"could not build the usage book for {season}"
        store.record_run("usage", False, summary, started, iso(now_utc()))
        print("usage:", summary)
        return None
    # keep it small: only the positions the column covers, and only prior-season rows for players
    # who have already appeared this season (those are the only historical pairs that can fire)
    cur = {r["pid"] for r in u.rows if r["season"] == season}
    u.rows = [r for r in u.rows if r["pos"] in KEEP_POS and (r["season"] == season or r["pid"] in cur)]
    u.prior = {k: v for k, v in u.prior.items() if v.get("pos") in KEEP_POS}
    compact = usagedata.to_compact(u, season, {season, season - 1})
    ids, how = id_map(data_dir, u)
    compact["sleeper_to_gsis"] = ids
    compact["id_map_sources"] = how
    compact["pulled_at_utc"] = iso(now_utc())
    compact["source"] = {k: history.load_manifest()["files"].get(os.path.basename(v or ""), {}).get("url")
                         for k, v in got.items() if v}
    compact["weeks"] = sorted({r["week"] for r in u.rows if r["season"] == season})
    path = os.path.join(data_dir, "usage", str(season), "usage.json")
    store.write_json(path, compact, compact=True)
    summary = (f"{len(compact['weeks'])} weeks of {season} usage, {len(cur):,} players with a stat row, "
               f"{len(ids):,} Sleeper ids mapped ({how['gsis_field']} from Sleeper, {how['rankings']} from the rankings file, "
               f"{how['name_team']} by name), {os.path.getsize(path):,} bytes")
    store.record_run("usage", True, summary, started, iso(now_utc()))
    print("usage:", summary)
    return compact


def load(data_dir=None, season=None):
    """The committed usage book, or None. No network."""
    d = data_dir or config.DATA_DIR
    season = str(season or config.SEASON_HINT)
    raw = store.read_json(os.path.join(d, "usage", season, "usage.json"), None)
    if not raw or not raw.get("rows"):
        return None, None
    return usagedata.from_compact(raw), raw
