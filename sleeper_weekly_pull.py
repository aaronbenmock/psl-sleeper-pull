#!/usr/bin/env python3
"""
Sleeper weekly pull for Pretend Sportsball League '26.

Pulls, with NO third-party packages (stdlib only):
  1. Completed week: actual vs projected points, per starter/bench player, plus matchup result
  2. Upcoming week: my roster split into starters / bench / IR with projections + injury status
  3. Waiver wire: every unrostered QB/RB/WR/TE/DEF ranked by upcoming-week projection,
     with last week's actual points and trending add counts

Projected points are computed from Sleeper's raw projected stat lines x this league's
scoring_settings (Sleeper stat keys match scoring keys 1:1), so bonuses and DEF TFL/sack
scoring are applied the same way Sleeper does.

Usage:
  python sleeper_weekly_pull.py                      # auto-detect weeks
  python sleeper_weekly_pull.py --completed-week 3   # override
Outputs to ./data/<season>/ plus ./data/latest.json and ./data/latest.md
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request
import urllib.error

LEAGUE_ID = os.environ.get("SLEEPER_LEAGUE_ID", "1318619274968829952")
USERNAME = os.environ.get("SLEEPER_USERNAME", "Mockstar")
BASE = "https://api.sleeper.app"
FANTASY_POS = ["QB", "RB", "WR", "TE", "DEF"]
WAIVER_TOP_N = 25          # per position in the ranked waiver list
TRENDING_LOOKBACK_H = 72   # Sun night -> Wed morning covers post-game adds
VERSION = "1.0"


# ---------------------------------------------------------------- HTTP
def get(path, retries=4):
    url = path if path.startswith("http") else BASE + path
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "psl-weekly-pull/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET {url} failed after {retries} tries: {last}")


# ---------------------------------------------------------------- scoring
def league_points(stats, scoring):
    """Sum stat * scoring weight for every key present in both. None if no stats."""
    if not stats:
        return None
    return round(sum(float(v) * scoring[k] for k, v in stats.items()
                     if k in scoring and isinstance(v, (int, float))), 2)


def stat_map(rows):
    """projections/stats endpoints return a list; key it by player_id."""
    out = {}
    for row in rows or []:
        pid = row.get("player_id")
        if pid:
            out[str(pid)] = row
    return out


def pull_position_rows(kind, season, week):
    """kind = 'projections' or 'stats'. Pull all fantasy positions in one call."""
    qs = "&".join(f"position[]={p}" for p in FANTASY_POS)
    return stat_map(get(f"/{kind}/nfl/{season}/{week}?season_type=regular&{qs}"))


# ---------------------------------------------------------------- players
def player_info(pid, players):
    p = players.get(pid) or {}
    if p.get("position") == "DEF" or (not p and pid.isalpha()):
        return {"player_id": pid, "name": f"{pid} DEF", "pos": "DEF", "team": pid,
                "injury_status": None, "depth_chart_order": None}
    name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or pid
    return {
        "player_id": pid,
        "name": name,
        "pos": p.get("position"),
        "team": p.get("team"),
        "injury_status": p.get("injury_status"),
        "injury_body_part": p.get("injury_body_part"),
        "depth_chart_order": p.get("depth_chart_order"),
        "bye_or_status": p.get("status"),
    }


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--completed-week", type=int)
    ap.add_argument("--out", default="data")
    args = ap.parse_args()

    state = get("/v1/state/nfl")
    league = get(f"/v1/league/{LEAGUE_ID}")
    season = str(league["season"])
    scoring = {k: float(v) for k, v in league["scoring_settings"].items()}

    # ---- figure out which week just finished
    if args.completed_week:
        completed = args.completed_week
    else:
        w = int(state.get("week") or 0)
        wk_matchups = get(f"/v1/league/{LEAGUE_ID}/matchups/{w}") if w else []
        has_points = any((m.get("points") or 0) != 0 for m in wk_matchups)
        completed = w if has_points else w - 1
    upcoming = completed + 1
    if completed < 1:
        sys.exit(f"No completed regular-season week yet (state: {state}). Nothing to pull.")

    users = get(f"/v1/league/{LEAGUE_ID}/users")
    rosters = get(f"/v1/league/{LEAGUE_ID}/rosters")
    players = get("/v1/players/nfl")  # ~5MB; Sleeper asks for <=1/day, we do 1/week
    trending = get(f"/v1/players/nfl/trending/add?lookback_hours={TRENDING_LOOKBACK_H}&limit=100")
    trend_ct = {str(t["player_id"]): t["count"] for t in trending}

    user_by_id = {u["user_id"]: u for u in users}
    me = next((u for u in users if (u.get("display_name") or "").lower() == USERNAME.lower()
               or (u.get("username") or "").lower() == USERNAME.lower()), None)
    if not me:
        sys.exit(f"Username {USERNAME} not found in league users")
    my_roster = next(r for r in rosters if r.get("owner_id") == me["user_id"])
    my_rid = my_roster["roster_id"]

    def team_name(roster_id):
        r = next((x for x in rosters if x["roster_id"] == roster_id), {})
        u = user_by_id.get(r.get("owner_id"), {})
        return (u.get("metadata") or {}).get("team_name") or u.get("display_name") or f"roster {roster_id}"

    # ---- 1. completed week: projected vs actual
    proj_done = pull_position_rows("projections", season, completed)
    stats_done = pull_position_rows("stats", season, completed)
    matchups = get(f"/v1/league/{LEAGUE_ID}/matchups/{completed}")

    def proj_pts(pid, table):
        row = table.get(pid)
        return league_points(row.get("stats"), scoring) if row else None

    league_week = []
    for m in matchups:
        starters = [s for s in m.get("starters") or [] if s and s != "0"]
        proj_total = round(sum(proj_pts(s, proj_done) or 0 for s in starters), 2)
        league_week.append({"roster_id": m["roster_id"], "team": team_name(m["roster_id"]),
                            "matchup_id": m.get("matchup_id"), "actual": m.get("points"),
                            "projected_starters_total": proj_total})

    mine = next(m for m in matchups if m["roster_id"] == my_rid)
    opp = next((m for m in matchups if m.get("matchup_id") == mine.get("matchup_id")
                and m["roster_id"] != my_rid), None)
    pp = mine.get("players_points") or {}
    my_starters_done = [s for s in mine.get("starters") or [] if s and s != "0"]

    def done_row(pid, slot):
        info = player_info(pid, players)
        proj = proj_pts(pid, proj_done)
        act = pp.get(pid)
        info.update({"slot": slot, "projected": proj, "actual": act,
                     "diff": round(act - proj, 2) if act is not None and proj is not None else None})
        return info

    slots = [p for p in league["roster_positions"] if p not in ("BN", "IR")]
    completed_block = {
        "week": completed,
        "my_team": team_name(my_rid),
        "my_actual": mine.get("points"),
        "my_projected": round(sum(proj_pts(s, proj_done) or 0 for s in my_starters_done), 2),
        "opponent": team_name(opp["roster_id"]) if opp else None,
        "opponent_actual": opp.get("points") if opp else None,
        "opponent_projected": round(sum(proj_pts(s, proj_done) or 0 for s in opp.get("starters") or []
                                        if s and s != "0"), 2) if opp else None,
        "result": (None if not opp else "W" if mine["points"] > opp["points"]
                   else "L" if mine["points"] < opp["points"] else "T"),
        "starters": [done_row(pid, slots[i] if i < len(slots) else "?")
                     for i, pid in enumerate(mine.get("starters") or []) if pid and pid != "0"],
        "bench": [done_row(pid, "BN") for pid in (mine.get("players") or [])
                  if pid not in my_starters_done],
        "league_scoreboard": sorted(league_week, key=lambda x: -(x["actual"] or 0)),
    }

    # ---- 2. upcoming week: my lineup as currently set
    proj_next = pull_position_rows("projections", season, upcoming)

    def next_row(pid, slot):
        info = player_info(pid, players)
        row = proj_next.get(pid) or {}
        info.update({"slot": slot, "projected": league_points(row.get("stats"), scoring),
                     "opponent": row.get("opponent"),
                     "on_bye": bool(proj_next) and pid not in proj_next})  # no projection row = bye or ruled out
        return info

    cur_starters = [s for s in my_roster.get("starters") or []]
    reserve = my_roster.get("reserve") or []
    upcoming_block = {
        "week": upcoming,
        "record": {k: my_roster["settings"].get(k) for k in ("wins", "losses", "ties")},
        "waiver_budget_used": my_roster["settings"].get("waiver_budget_used"),
        "waiver_budget_total": league["settings"].get("waiver_budget"),
        "starters": [next_row(pid, slots[i] if i < len(slots) else "?") if pid and pid != "0"
                     else {"slot": slots[i] if i < len(slots) else "?", "name": "EMPTY"}
                     for i, pid in enumerate(cur_starters)],
        "bench": [next_row(pid, "BN") for pid in my_roster.get("players") or []
                  if pid not in cur_starters and pid not in reserve],
        "ir": [next_row(pid, "IR") for pid in reserve],
    }

    # ---- 3. waiver wire
    rostered = set()
    for r in rosters:
        for key in ("players", "reserve", "taxi"):
            rostered.update(r.get(key) or [])

    pool = []
    candidates = set(proj_next) | set(trend_ct)
    for pid, p in players.items():
        if p.get("team") and p.get("position") in FANTASY_POS and p.get("active", True):
            candidates.add(pid)
    for pid in candidates:
        if pid in rostered:
            continue
        info = player_info(pid, players)
        if info["pos"] not in FANTASY_POS or not info["team"]:
            continue
        last = stats_done.get(pid)
        info.update({
            "proj_next_week": league_points((proj_next.get(pid) or {}).get("stats"), scoring),
            "opponent_next_week": (proj_next.get(pid) or {}).get("opponent"),
            f"actual_week_{completed}": league_points(last.get("stats"), scoring) if last else None,
            f"projected_week_{completed}": proj_pts(pid, proj_done),
            f"trending_adds_{TRENDING_LOOKBACK_H}h": trend_ct.get(pid, 0),
        })
        pool.append(info)

    waivers = {}
    for pos in FANTASY_POS:
        ranked = sorted([x for x in pool if x["pos"] == pos],
                        key=lambda x: (-(x["proj_next_week"] or 0), -x[f"trending_adds_{TRENDING_LOOKBACK_H}h"]))
        waivers[pos] = ranked[:WAIVER_TOP_N]
    hot = sorted([x for x in pool if x[f"trending_adds_{TRENDING_LOOKBACK_H}h"] > 0],
                 key=lambda x: -x[f"trending_adds_{TRENDING_LOOKBACK_H}h"])

    # ---- write
    now = dt.datetime.now(dt.timezone.utc)
    result = {
        "meta": {"script_version": VERSION, "pulled_at_utc": now.isoformat(timespec="seconds"),
                 "league": league["name"], "league_id": LEAGUE_ID, "season": season,
                 "nfl_state": state, "completed_week": completed, "upcoming_week": upcoming,
                 "notes": ["projected = Sleeper projected stat line x league scoring_settings",
                           "Sleeper DEF projections omit 3-and-outs and 4th-down stops, so DEF projections run low",
                           "waiver list = unrostered players on an NFL team; FAAB so all are claimable before Thu 2AM"]},
        "completed_week": completed_block,
        "upcoming_week": upcoming_block,
        "waivers_by_position": waivers,
        "waivers_trending": hot,
    }

    season_dir = os.path.join(args.out, season)
    os.makedirs(season_dir, exist_ok=True)
    stem = f"week{upcoming:02d}_pull_{now:%Y-%m-%d}"
    for path in (os.path.join(season_dir, stem + ".json"), os.path.join(args.out, "latest.json")):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
    md = render_md(result)
    for path in (os.path.join(season_dir, stem + ".md"), os.path.join(args.out, "latest.md")):
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
    print(f"Wrote {stem} (completed wk {completed}, upcoming wk {upcoming}, waiver pool {len(pool)})")


def fmt(v):
    return "-" if v is None else (f"{v:.1f}" if isinstance(v, float) else str(v))


def render_md(r):
    c, u, m = r["completed_week"], r["upcoming_week"], r["meta"]
    L = [f"# {m['league']} weekly pull",
         f"Pulled {m['pulled_at_utc']} UTC. Completed week {c['week']}, upcoming week {u['week']}.", "",
         f"## Week {c['week']} result: {c['result']}",
         f"{c['my_team']} {fmt(c['my_actual'])} (proj {fmt(c['my_projected'])}) vs "
         f"{c['opponent']} {fmt(c['opponent_actual'])} (proj {fmt(c['opponent_projected'])})", "",
         "| Slot | Player | Pos | Team | Proj | Actual | Diff |", "|---|---|---|---|---|---|---|"]
    for p in c["starters"] + c["bench"]:
        L.append(f"| {p['slot']} | {p['name']} | {p['pos']} | {p['team']} | {fmt(p['projected'])} | "
                 f"{fmt(p['actual'])} | {fmt(p['diff'])} |")
    L += ["", "### League scoreboard", "| Team | Actual | Proj |", "|---|---|---|"]
    for t in c["league_scoreboard"]:
        L.append(f"| {t['team']} | {fmt(t['actual'])} | {fmt(t['projected_starters_total'])} |")
    L += ["", f"## Week {u['week']} lineup as currently set",
          f"Record {u['record']}. FAAB used {u['waiver_budget_used']}/{u['waiver_budget_total']}.", "",
          "| Slot | Player | Pos | Team | Opp | Proj | Injury |", "|---|---|---|---|---|---|---|"]
    for p in u["starters"] + u["bench"] + u["ir"]:
        L.append(f"| {p['slot']} | {p.get('name')} | {p.get('pos')} | {p.get('team')} | "
                 f"{'BYE/OUT' if p.get('on_bye') else fmt(p.get('opponent'))} | {fmt(p.get('projected'))} | "
                 f"{fmt(p.get('injury_status'))} |")
    wk = c["week"]
    for pos, rows in r["waivers_by_position"].items():
        L += ["", f"## Waivers: {pos} (top {len(rows)} by week {u['week']} projection)",
              f"| Player | Team | Opp | Proj wk{u['week']} | Actual wk{wk} | Adds 72h | Injury |",
              "|---|---|---|---|---|---|---|"]
        for p in rows:
            L.append(f"| {p['name']} | {p['team']} | {fmt(p['opponent_next_week'])} | {fmt(p['proj_next_week'])} | "
                     f"{fmt(p[f'actual_week_{wk}'])} | {p['trending_adds_72h']} | {fmt(p['injury_status'])} |")
    L += ["", "## Trending adds (unrostered)", "| Player | Pos | Team | Adds 72h | Proj next |", "|---|---|---|---|---|"]
    for p in r["waivers_trending"][:30]:
        L.append(f"| {p['name']} | {p['pos']} | {p['team']} | {p['trending_adds_72h']} | {fmt(p['proj_next_week'])} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
