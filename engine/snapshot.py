"""Pre-kickoff projection snapshot: frozen, timestamped, committed.

Every snapshot records, for the week whose games are next:
  players[pid] = {p: league-scored projection, a: actual points so far (None before kickoff),
                  opp, date, team}
  teams_started = NFL teams that already have a stat row this week (their game has begun)
  lineups[roster_id] = starters as set in Sleeper at that moment

"Pre-kickoff" for a player is decided later, per player, by teams_started, not by the clock.
A snapshot that fires late is therefore never mistaken for a pre-kickoff one: the accuracy
module only uses a snapshot for a player whose team had not started when it was taken.

Files: data/snapshots/<season>/weekNN/snap_<UTC stamp>.json and data/snapshots/<season>/index.json
"""
import os

from . import config, store
from .sleeper import get, league_points, pull_position_rows, detect_weeks, load_cached_players_only, player_info
from .timeutil import now_utc, iso, to_central


def label_for(local_dt):
    h = local_dt.hour
    wd = local_dt.strftime("%a").lower()
    if h < 9:
        part = "early"
    elif h < 14:
        part = "late_am"
    else:
        part = "pm"
    return f"{wd}_{part}"


def run(out_dir=None, week_override=None):
    data_dir = out_dir or config.DATA_DIR
    started = iso(now_utc())
    state = get("/v1/state/nfl")
    league = get(f"/v1/league/{config.LEAGUE_ID}")
    season = str(league["season"])
    scoring = {k: float(v) for k, v in (league.get("scoring_settings") or {}).items()}
    proj_cache = {}
    if week_override:
        week = week_override
    else:
        completed, week, how = detect_weeks(state, season, proj_cache=proj_cache)
    proj = proj_cache.get(week) or pull_position_rows("projections", season, week)
    stats = pull_position_rows("stats", season, week)
    rosters = get(f"/v1/league/{config.LEAGUE_ID}/rosters")
    players, _ = load_cached_players_only(data_dir)

    teams_started = set()
    for pid, row in stats.items():
        st = row.get("stats") or {}
        if st and any(isinstance(v, (int, float)) and v for v in st.values()):
            t = row.get("team") or (players.get(pid) or {}).get("team")
            if t:
                teams_started.add(t)
            opp = row.get("opponent")
            if opp:
                teams_started.add(opp)

    rows = {}
    for pid, pr in proj.items():
        pts = league_points(pr.get("stats"), scoring, config.PROJ_EXCLUDE)
        info = player_info(pid, players)
        team = info["team"] or pr.get("team")
        if pts is None:
            continue
        srow = stats.get(pid) or {}
        act = league_points(srow.get("stats"), scoring) if srow.get("stats") else None
        rows[pid] = {"p": pts, "a": act, "opp": pr.get("opponent"), "date": pr.get("date"), "team": team,
                     "pos": info["pos"], "started": team in teams_started}

    now = now_utc()
    local = to_central(now)
    label = label_for(local)
    meta = {"season": season, "week": week, "taken_at_utc": iso(now), "taken_at_central": local.isoformat(),
            "label": label, "n_players": len(rows), "n_teams_started": len(teams_started),
            "n_players_pre_kickoff": sum(1 for r in rows.values() if not r["started"]),
            "nfl_state_week": state.get("week")}
    snap = {"meta": meta, "teams_started": sorted(teams_started),
            "lineups": {str(r["roster_id"]): r.get("starters") or [] for r in rosters},
            "players": rows}
    stamp = now.strftime("%Y-%m-%dT%H%MZ")
    path = os.path.join(data_dir, "snapshots", season, f"week{week:02d}", f"snap_{stamp}.json")
    store.write_json(path, snap, compact=True)

    idx_path = os.path.join(data_dir, "snapshots", season, "index.json")
    idx = store.read_json(idx_path, {"snapshots": []}) or {"snapshots": []}
    idx["snapshots"] = [s for s in idx["snapshots"] if s.get("path") != path.replace("\\", "/")]
    idx["snapshots"].append(dict(meta, path=path.replace("\\", "/")))
    idx["snapshots"].sort(key=lambda s: s["taken_at_utc"])
    store.write_json(idx_path, idx)
    summary = (f"week {week} {label}: {len(rows)} projections, {len(teams_started)} NFL teams already started, "
               f"{meta['n_players_pre_kickoff']} players still pre-kickoff")
    store.record_run("snapshot", True, summary, started, iso(now_utc()), extra={"week": week, "label": label})
    print("snapshot:", summary)
    return snap
