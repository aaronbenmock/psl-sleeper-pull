"""Daily injury tracker (machine data, no news source).

Records the eight Sleeper injury/practice fields for every rostered player in the league,
diffs against the previous day's file, and keeps rosters.json current so the league view
sees daily roster moves. Aaron's roster is flagged so the dashboard can lead with it.

Files:
  data/injuries/<season>/injuries_<date>.json   full table for the day
  data/injuries/<season>/diff_<date>.json       what changed since the last table
  data/league/rosters.json                      refreshed daily
"""
import os

from . import config, store
from .sleeper import get, load_players, find_me, team_name_fn, player_info
from .timeutil import now_utc, iso, to_central

FIELDS = ["injury_status", "injury_body_part", "injury_start_date", "injury_notes",
          "practice_participation", "practice_description", "news_updated", "depth_chart_order",
          "team", "status"]


def snapshot_table(players, rosters, users, my_rid, slots):
    team_name = team_name_fn(users, rosters)
    table = {}
    for r in rosters:
        starters = r.get("starters") or []
        reserve = r.get("reserve") or []
        for pid in (r.get("players") or []) + [x for x in reserve if x not in (r.get("players") or [])]:
            if not pid or pid == "0":
                continue
            info = player_info(pid, players)
            p = players.get(pid) or {}
            row = {"name": info["name"], "pos": info["pos"], "roster_id": r["roster_id"],
                   "team_name": team_name(r["roster_id"]), "is_mine": r["roster_id"] == my_rid,
                   "slot": (slots[starters.index(pid)] if pid in starters and starters.index(pid) < len(slots)
                            else "IR" if pid in reserve else "BN")}
            for f in FIELDS:
                row[f] = p.get(f)
            table[pid] = row
    return table


def diff_tables(prev, cur):
    changes = []
    for pid, row in cur.items():
        old = (prev or {}).get(pid)
        if old is None:
            if row.get("injury_status") or row.get("practice_participation"):
                changes.append({"player_id": pid, "name": row["name"], "pos": row["pos"], "team": row.get("team"),
                                "roster_id": row["roster_id"], "team_name": row["team_name"], "is_mine": row["is_mine"],
                                "slot": row["slot"], "kind": "new_on_roster", "fields": {}})
            continue
        fields = {}
        for f in FIELDS:
            if f in ("team",):
                continue
            if (old.get(f) or None) != (row.get(f) or None):
                fields[f] = {"from": old.get(f), "to": row.get(f)}
        if fields:
            changes.append({"player_id": pid, "name": row["name"], "pos": row["pos"], "team": row.get("team"),
                            "roster_id": row["roster_id"], "team_name": row["team_name"], "is_mine": row["is_mine"],
                            "slot": row["slot"], "kind": "changed", "fields": fields})
    for pid, old in (prev or {}).items():
        if pid not in cur and old.get("is_mine"):
            changes.append({"player_id": pid, "name": old["name"], "pos": old["pos"], "team": old.get("team"),
                            "roster_id": old["roster_id"], "team_name": old["team_name"], "is_mine": True,
                            "slot": old["slot"], "kind": "left_roster", "fields": {}})
    changes.sort(key=lambda c: (not c["is_mine"], c["team_name"], c["name"]))
    return changes


def run(out_dir=None):
    data_dir = out_dir or config.DATA_DIR
    started = iso(now_utc())
    state = get("/v1/state/nfl")
    league = get(f"/v1/league/{config.LEAGUE_ID}")
    season = str(league["season"])
    users = get(f"/v1/league/{config.LEAGUE_ID}/users")
    rosters = get(f"/v1/league/{config.LEAGUE_ID}/rosters")
    rostered = set()
    for r in rosters:
        for key in ("players", "reserve", "taxi"):
            rostered.update(r.get(key) or [])
    players, pmeta = load_players(data_dir, keep_ids=rostered)
    me = find_me(users)
    my_rid = next((r["roster_id"] for r in rosters if me and r.get("owner_id") == me["user_id"]), None)
    slots = [p for p in league["roster_positions"] if p not in ("BN", "IR")]

    table = snapshot_table(players, rosters, users, my_rid, slots)
    now = now_utc()
    day = to_central(now).strftime("%Y-%m-%d")
    inj_dir = os.path.join(data_dir, "injuries", season)
    prev_path = store.latest_file(os.path.join(inj_dir, "injuries_*.json"))
    prev = store.read_json(prev_path, {}) or {}
    if prev_path and os.path.basename(prev_path) == f"injuries_{day}.json":
        # second run on the same day: diff against the day before, not against ourselves
        older = [f for f in store.list_files(os.path.join(inj_dir, "injuries_*.json")) if f != prev_path]
        prev = store.read_json(older[-1], {}) if older else {}
    changes = diff_tables(prev.get("players") if prev else {}, table)

    store.write_json(os.path.join(inj_dir, f"injuries_{day}.json"),
                     {"date_central": day, "pulled_at_utc": iso(now), "players_cache": pmeta,
                      "nfl_week": state.get("week"), "players": table}, compact=True)
    store.write_json(os.path.join(inj_dir, f"diff_{day}.json"),
                     {"date_central": day, "pulled_at_utc": iso(now), "compared_to": (prev or {}).get("date_central"),
                      "n_changes": len(changes), "n_mine": sum(1 for c in changes if c["is_mine"]),
                      "changes": changes})
    store.write_json(os.path.join(data_dir, "league", "rosters.json"),
                     {"pulled_at_utc": iso(now), "rosters": rosters})
    store.write_json(os.path.join(data_dir, "league", "users.json"),
                     [{"user_id": u.get("user_id"), "display_name": u.get("display_name"),
                       "team_name": (u.get("metadata") or {}).get("team_name")} for u in users])
    mine_flagged = sum(1 for r in table.values() if r["is_mine"] and r.get("injury_status"))
    summary = (f"{len(table)} rostered players tracked, {len(changes)} changes since {(prev or {}).get('date_central') or 'never'}, "
               f"{mine_flagged} of mine carry an injury tag, players cache {'reused' if pmeta.get('reused') else 'pulled'}")
    store.record_run("injuries", True, summary, started, iso(now_utc()))
    print("injuries:", summary)
    return changes
