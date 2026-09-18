"""Weekly Sleeper pull, v1.2. Extends the v1.1 script without changing what it already wrote.

Still written (v1.1 shape): data/latest.json, data/latest.md, data/<season>/weekNN_pull_<date>.{json,md}
New in v1.2:
  data/league/league.json            league settings, scoring, roster slots (validation of the 2-0 record)
  data/league/users.json, rosters.json
  data/league/matchups/weekNN.json   every week Sleeper returns (past and future pairings)
  data/league/transactions.json      waiver/free-agent/trade log by week (drop dates -> waiver clocks)
  data/weeks/<season>/weekNN_scored.json  every fantasy player's projected and actual points for each
                                     completed week, league-scored, with the DEF stat components that
                                     Sleeper never projects (quantifies the DEF bias every week)
  data/players/players_slim.json     via sleeper.load_players (once per day, shared with the injury job)
"""
import datetime as dt
import os

from . import config, store
from .sleeper import (get, league_points, points_by_category, pull_position_rows, player_info,
                      load_players, find_me, team_name_fn, detect_weeks)
from .timeutil import now_utc, iso


def _scoring(league):
    return {k: float(v) for k, v in (league.get("scoring_settings") or {}).items()}


def score_week(season, week, scoring, players, proj_rows=None, stats_rows=None):
    """League-scored projected vs actual for every player with a row that week."""
    proj = proj_rows if proj_rows is not None else pull_position_rows("projections", season, week)
    stats = stats_rows if stats_rows is not None else pull_position_rows("stats", season, week)
    rows = {}
    for pid in set(proj) | set(stats):
        info = player_info(pid, players)
        if info["pos"] not in config.FANTASY_POS:
            continue
        pr = proj.get(pid) or {}
        sr = stats.get(pid) or {}
        st = sr.get("stats") or {}
        row = {
            "name": info["name"], "pos": info["pos"], "team": info["team"] or pr.get("team") or sr.get("team"),
            "opp": pr.get("opponent") or sr.get("opponent"), "date": pr.get("date") or sr.get("date"),
            "proj": league_points(pr.get("stats"), scoring, config.PROJ_EXCLUDE),
            "actual": league_points(st, scoring) if st else None,
            "gp": st.get("gp"),
        }
        if info["pos"] == "DEF":
            row["unprojected_pts"] = points_by_category(st, scoring, config.DEF_UNPROJECTED_KEYS)
            row["def_stats"] = {k: st.get(k) for k in ("def_3_and_out", "def_4_and_stop", "sack", "int", "fum_rec",
                                                        "tkl_loss", "def_td", "pts_allow", "safe", "ff", "blk_kick",
                                                        "yds_allow") if k in st}
            row["proj_stats"] = {k: v for k, v in (pr.get("stats") or {}).items() if k in scoring}
        rows[pid] = row
    return {"season": season, "week": week, "scored_at_utc": iso(now_utc()),
            "n_players": len(rows), "players": rows}


def run(completed_override=None, out_dir=None, force_rescore=False):
    data_dir = out_dir or config.DATA_DIR
    started = iso(now_utc())
    state = get("/v1/state/nfl")
    league = get(f"/v1/league/{config.LEAGUE_ID}")
    season = str(league["season"])
    scoring = _scoring(league)
    users = get(f"/v1/league/{config.LEAGUE_ID}/users")
    rosters = get(f"/v1/league/{config.LEAGUE_ID}/rosters")

    proj_cache = {}
    if completed_override:
        completed, upcoming, how = completed_override, completed_override + 1, "override"
    else:
        completed, upcoming, how = detect_weeks(state, season, proj_cache=proj_cache)
    if completed < 1:
        raise SystemExit(f"No completed regular-season week yet (state: {state}). Nothing to pull.")

    rostered_ids = set()
    for r in rosters:
        for key in ("players", "reserve", "taxi"):
            rostered_ids.update(r.get(key) or [])
    players, pmeta = load_players(data_dir, keep_ids=rostered_ids)
    trending = get(f"/v1/players/nfl/trending/add?lookback_hours={config.TRENDING_LOOKBACK_H}&limit=100")
    trend_ct = {str(t["player_id"]): t["count"] for t in trending}

    me = find_me(users)
    if not me:
        raise SystemExit(f"Username {config.USERNAME} not found in league users")
    my_roster = next(r for r in rosters if r.get("owner_id") == me["user_id"])
    my_rid = my_roster["roster_id"]
    team_name = team_name_fn(users, rosters)

    # ---- 1. completed week: projected vs actual (v1.1 block, unchanged shape)
    proj_done = proj_cache.get(completed) or pull_position_rows("projections", season, completed)
    stats_done = pull_position_rows("stats", season, completed)
    matchups = get(f"/v1/league/{config.LEAGUE_ID}/matchups/{completed}")

    def proj_pts(pid, table):
        row = table.get(pid)
        return league_points(row.get("stats"), scoring, config.PROJ_EXCLUDE) if row else None

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
        "result": (None if not opp else "W" if (mine.get("points") or 0) > (opp.get("points") or 0)
                   else "L" if (mine.get("points") or 0) < (opp.get("points") or 0) else "T"),
        "starters": [done_row(pid, slots[i] if i < len(slots) else "?")
                     for i, pid in enumerate(mine.get("starters") or []) if pid and pid != "0"],
        "bench": [done_row(pid, "BN") for pid in (mine.get("players") or [])
                  if pid not in my_starters_done],
        "league_scoreboard": sorted(league_week, key=lambda x: -(x["actual"] or 0)),
    }

    # ---- 2. upcoming week: my lineup as currently set
    proj_next = proj_cache.get(upcoming) or pull_position_rows("projections", season, upcoming)

    def next_row(pid, slot):
        info = player_info(pid, players)
        row = proj_next.get(pid) or {}
        info.update({"slot": slot, "projected": league_points(row.get("stats"), scoring, config.PROJ_EXCLUDE),
                     "opponent": row.get("opponent"),
                     "on_bye": bool(proj_next) and pid not in proj_next})
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
    pool = []
    candidates = set(proj_next) | set(trend_ct)
    for pid, p in players.items():
        if p.get("team") and p.get("position") in config.FANTASY_POS and p.get("active", True):
            candidates.add(pid)
    for pid in candidates:
        if pid in rostered_ids:
            continue
        info = player_info(pid, players)
        if info["pos"] not in config.FANTASY_POS or not info["team"]:
            continue
        last = stats_done.get(pid)
        info.update({
            "proj_next_week": league_points((proj_next.get(pid) or {}).get("stats"), scoring, config.PROJ_EXCLUDE),
            "opponent_next_week": (proj_next.get(pid) or {}).get("opponent"),
            f"actual_week_{completed}": league_points(last.get("stats"), scoring) if last else None,
            f"projected_week_{completed}": proj_pts(pid, proj_done),
            f"trending_adds_{config.TRENDING_LOOKBACK_H}h": trend_ct.get(pid, 0),
        })
        pool.append(info)
    tkey = f"trending_adds_{config.TRENDING_LOOKBACK_H}h"
    waivers = {}
    for pos in config.FANTASY_POS:
        ranked = sorted([x for x in pool if x["pos"] == pos],
                        key=lambda x: (-(x["proj_next_week"] or 0), -x[tkey]))
        waivers[pos] = ranked[:config.WAIVER_TOP_N]
    hot = sorted([x for x in pool if x[tkey] > 0], key=lambda x: -x[tkey])

    # ---- 4. NEW in v1.2: league-wide raw data for the league view and accuracy work
    league_dir = os.path.join(data_dir, "league")
    store.write_json(os.path.join(league_dir, "league.json"),
                     {"pulled_at_utc": iso(now_utc()), "name": league.get("name"), "season": season,
                      "status": league.get("status"), "settings": league.get("settings"),
                      "scoring_settings": league.get("scoring_settings"),
                      "roster_positions": league.get("roster_positions"),
                      "total_rosters": league.get("total_rosters"), "nfl_state": state})
    store.write_json(os.path.join(league_dir, "users.json"),
                     [{"user_id": u.get("user_id"), "display_name": u.get("display_name"),
                       "team_name": (u.get("metadata") or {}).get("team_name")} for u in users])
    store.write_json(os.path.join(league_dir, "rosters.json"),
                     {"pulled_at_utc": iso(now_utc()), "rosters": rosters})
    weeks_available = []
    last_week = int((league.get("settings") or {}).get("playoff_week_start") or 15) + 3
    for wk in range(1, min(last_week, 18) + 1):
        try:
            m = get(f"/v1/league/{config.LEAGUE_ID}/matchups/{wk}")
        except RuntimeError:
            break
        if not m:
            break
        store.write_json(os.path.join(league_dir, "matchups", f"week{wk:02d}.json"), m, compact=True)
        weeks_available.append(wk)
    tx = {}
    for wk in range(1, upcoming + 1):
        try:
            rows = get(f"/v1/league/{config.LEAGUE_ID}/transactions/{wk}")
        except RuntimeError:
            rows = []
        tx[str(wk)] = [{k: t.get(k) for k in ("transaction_id", "type", "status", "roster_ids", "adds", "drops",
                                                "settings", "created", "status_updated", "leg", "creator")}
                       for t in rows or []]
    store.write_json(os.path.join(league_dir, "transactions.json"),
                     {"pulled_at_utc": iso(now_utc()), "by_week": tx})

    scored_files = []
    for wk in range(1, completed + 1):
        path = os.path.join(data_dir, "weeks", season, f"week{wk:02d}_scored.json")
        if os.path.exists(path) and not force_rescore and wk < completed:
            continue
        if wk == completed:
            scored = score_week(season, wk, scoring, players, proj_done, stats_done)
        else:
            scored = score_week(season, wk, scoring, players)
        store.write_json(path, scored, compact=True)
        scored_files.append(path)

    # record validation: does the league count a median game as well as the head-to-head game?
    total_wins = sum((r.get("settings") or {}).get("wins") or 0 for r in rosters)
    total_losses = sum((r.get("settings") or {}).get("losses") or 0 for r in rosters)
    median_flag = (league.get("settings") or {}).get("league_average_match")
    record_check = {
        "completed_weeks": completed,
        "league_average_match_setting": median_flag,
        "sum_of_wins": total_wins, "sum_of_losses": total_losses,
        "expected_wins_h2h_only": 6 * completed, "expected_wins_with_median_game": 12 * completed,
        "verdict": ("median game ON: each team plays its opponent and the league median every week"
                    if median_flag == 1 or total_wins == 12 * completed
                    else "head-to-head only" if total_wins == 6 * completed else "unexplained"),
    }

    # ---- write (v1.1 files, plus v1.2 additions in meta)
    now = now_utc()
    result = {
        "meta": {"script_version": config.PULL_VERSION, "engine_version": config.ENGINE_VERSION,
                 "pulled_at_utc": now.isoformat(timespec="seconds"),
                 "league": league["name"], "league_id": config.LEAGUE_ID, "season": season,
                 "nfl_state": state, "completed_week": completed, "upcoming_week": upcoming,
                 "week_detection": how, "players_cache": pmeta,
                 "record_check": record_check,
                 "notes": ["projected = Sleeper projected stat line x league scoring_settings",
                           "Sleeper DEF projections omit 3-and-outs and 4th-down stops; weekNN_scored.json isolates those points",
                           "waiver list = unrostered players on an NFL team; FAAB so all are claimable before Thu 2AM"]},
        "completed_week": completed_block,
        "upcoming_week": upcoming_block,
        "waivers_by_position": waivers,
        "waivers_trending": hot,
    }
    season_dir = os.path.join(data_dir, season)
    os.makedirs(season_dir, exist_ok=True)
    stem = f"week{upcoming:02d}_pull_{now:%Y-%m-%d}"
    for path in (os.path.join(season_dir, stem + ".json"), os.path.join(data_dir, "latest.json")):
        store.write_json(path, result)
    md = render_md(result)
    for path in (os.path.join(season_dir, stem + ".md"), os.path.join(data_dir, "latest.md")):
        store.write_text(path, md)
    summary = (f"completed wk {completed}, upcoming wk {upcoming}, waiver pool {len(pool)}, "
               f"matchup weeks {len(weeks_available)}, scored files {len(scored_files)}, record check: {record_check['verdict']}")
    store.record_run("pull", True, summary, started, iso(now_utc()),
                     extra={"completed_week": completed, "upcoming_week": upcoming})
    print(f"Wrote {stem}: {summary}")
    return result


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
    tkey = f"trending_adds_{config.TRENDING_LOOKBACK_H}h"
    for pos, rows in r["waivers_by_position"].items():
        L += ["", f"## Waivers: {pos} (top {len(rows)} by week {u['week']} projection)",
              f"| Player | Team | Opp | Proj wk{u['week']} | Actual wk{wk} | Adds 72h | Injury |",
              "|---|---|---|---|---|---|---|"]
        for p in rows:
            L.append(f"| {p['name']} | {p['team']} | {fmt(p['opponent_next_week'])} | {fmt(p['proj_next_week'])} | "
                     f"{fmt(p[f'actual_week_{wk}'])} | {p[tkey]} | {fmt(p['injury_status'])} |")
    L += ["", "## Trending adds (unrostered)", "| Player | Pos | Team | Adds 72h | Proj next |", "|---|---|---|---|---|"]
    for p in r["waivers_trending"][:30]:
        L.append(f"| {p['name']} | {p['pos']} | {p['team']} | {p[tkey]} | {fmt(p['proj_next_week'])} |")
    if m.get("record_check"):
        L += ["", "## Validation", f"Record check: {m['record_check']['verdict']} "
              f"(sum of wins {m['record_check']['sum_of_wins']}, completed weeks {m['record_check']['completed_weeks']})."]
    return "\n".join(L) + "\n"
