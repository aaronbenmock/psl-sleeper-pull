"""Build a folder of fake Sleeper API responses for local testing.

api.sleeper.app is unreachable from Claude's environments, so the engine is exercised against
fixtures shaped like the real endpoints. Real values come from data/latest.json (one genuine
v1.1 pull) and reference/player_rankings_v2.0. Everything else (other teams' rosters, week 2
and 3 projections for players outside the pull) is synthesized and clearly not real.

Usage: python tools/make_fixtures.py <fixture_dir> [--scenario wednesday|sunday|monday]
Then:  SLEEPER_FIXTURE_DIR=<fixture_dir> python engine.py pull
"""
import csv
import json
import os
import random
import re
import sys

random.seed(7)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEAGUE_ID = "1318619274968829952"
BASE = "https://api.sleeper.app"

SCORING = {
    "pass_yd": 0.04, "pass_td": 6.0, "pass_2pt": 2.0, "pass_int": -2.0, "pass_td_40p": 1.0,
    "rush_yd": 0.1, "rush_td": 6.0, "rush_2pt": 2.0, "rush_td_40p": 1.0,
    "rec": 0.5, "rec_yd": 0.1, "rec_td": 6.0, "rec_2pt": 2.0, "rec_td_40p": 1.0,
    "bonus_rush_yd_100": 1.0, "bonus_rush_yd_200": 2.0, "bonus_rec_yd_100": 1.0, "bonus_rec_yd_200": 2.0,
    "bonus_pass_yd_300": 1.0, "bonus_pass_yd_400": 2.0,
    "fum": -1.0, "fum_lost": -1.0, "fum_rec_td": 6.0,
    "def_td": 6.0, "pts_allow": -0.1, "def_3_and_out": 0.5, "def_4_and_stop": 1.0, "sack": 1.0, "int": 2.0,
    "fum_rec": 2.0, "tkl_loss": 0.5, "safe": 4.0, "ff": 1.0, "blk_kick": 3.0, "def_2pt": 0.25,
    "st_td": 6.0, "st_ff": 1.0, "st_fum_rec": 1.0, "pr_yd": 0.05, "kr_yd": 0.05, "pr_td": 6.0, "kr_td": 6.0,
}
ROSTER_POSITIONS = ["QB", "RB", "RB", "WR", "WR", "FLEX", "FLEX", "DEF", "BN", "BN", "BN", "BN", "BN", "BN", "IR", "IR"]
TEAMS = ["ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
         "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS"]


sys.path.insert(0, ROOT)
from engine.sleeper import _fixture_name as fname  # noqa: E402


def write(d, path, obj):
    with open(os.path.join(d, fname(path)), "w", encoding="utf-8") as f:
        json.dump(obj, f)


def statline_for(pos, pts):
    """Invent a stat line that scores to roughly pts under SCORING."""
    pts = max(pts, 0.0)
    if pos == "QB":
        yd = pts / 0.04 * 0.55
        return {"pass_yd": round(yd), "pass_td": round(pts * 0.06, 2), "pass_int": round(0.4, 2), "rush_yd": round(pts * 0.6)}
    if pos == "RB":
        return {"rush_yd": round(pts * 4.5), "rush_td": round(pts * 0.04, 2), "rec": round(pts * 0.2, 2), "rec_yd": round(pts * 1.5)}
    if pos in ("WR", "TE"):
        return {"rec": round(pts * 0.35, 2), "rec_yd": round(pts * 4.2), "rec_td": round(pts * 0.035, 2)}
    if pos == "DEF":
        return {"sack": round(pts * 0.25, 2), "int": round(pts * 0.08, 2), "pts_allow": round(20 - pts, 1),
                "tkl_loss": round(pts * 0.4, 2), "def_td": round(pts * 0.01, 2)}
    return {}


def main():
    out = sys.argv[1]
    scenario = "wednesday"
    if "--scenario" in sys.argv:
        scenario = sys.argv[sys.argv.index("--scenario") + 1]
    os.makedirs(out, exist_ok=True)
    latest = json.load(open(os.path.join(ROOT, "data", "latest.json"), encoding="utf-8"))
    rank_rows = list(csv.DictReader(open(os.path.join(ROOT, "reference", "player_rankings_v2.0_2026-09-08.csv"),
                                         encoding="utf-8-sig")))
    def_rows = list(csv.DictReader(open(os.path.join(ROOT, "reference", "team_defense_rankings_v2.0_2026-09-08.csv"),
                                        encoding="utf-8-sig")))
    sched = list(csv.DictReader(open(os.path.join(ROOT, "reference", "team_schedule_2026.csv"), encoding="utf-8-sig")))
    game_date = {(r["team"], int(r["week"])): (r["gameday"], r["opponent"]) for r in sched}

    # ---- players
    players = {}
    for r in rank_rows:
        sid = (r.get("sleeper_id") or "").strip()
        if sid.endswith(".0"):
            sid = sid[:-2]
        if not sid:
            continue
        first, _, last = r["player_name"].partition(" ")
        players[sid] = {"player_id": sid, "first_name": first, "last_name": last, "full_name": r["player_name"],
                        "position": r["pos_2026"], "fantasy_positions": [r["pos_2026"]], "team": r["team_2026"],
                        "status": "Active", "active": True, "injury_status": None, "injury_body_part": None,
                        "injury_start_date": None, "injury_notes": None, "practice_participation": None,
                        "practice_description": None, "news_updated": None,
                        "depth_chart_order": int(float(r["depth_chart_order"])) if r.get("depth_chart_order") else None,
                        "depth_chart_position": r.get("depth_chart_position"), "years_exp": int(float(r["years_exp"] or 0)),
                        "age": 26, "search_rank": int(float(r["suggested_rank"]))}
    for t in TEAMS:
        players[t] = {"player_id": t, "first_name": t, "last_name": "Defense", "position": "DEF", "team": t,
                      "fantasy_positions": ["DEF"], "status": "Active", "active": True}
    # players from the genuine pull (my roster + waiver pool) with their real ids
    real_rows = latest["completed_week"]["starters"] + latest["completed_week"]["bench"] + \
        latest["upcoming_week"]["starters"] + latest["upcoming_week"]["bench"] + latest["upcoming_week"]["ir"]
    for pos_rows in latest["waivers_by_position"].values():
        real_rows += pos_rows
    real_rows += latest["waivers_trending"]
    for row in real_rows:
        pid = row.get("player_id")
        if not pid or row.get("name") == "EMPTY":
            continue
        if pid in players and row.get("pos") != "DEF":
            players[pid].update({"injury_status": row.get("injury_status"),
                                 "injury_body_part": row.get("injury_body_part"),
                                 "depth_chart_order": row.get("depth_chart_order"), "status": row.get("bye_or_status") or "Active"})
            continue
        if row.get("pos") == "DEF":
            continue
        first, _, last = (row.get("name") or pid).partition(" ")
        players[pid] = {"player_id": pid, "first_name": first, "last_name": last, "full_name": row.get("name"),
                        "position": row.get("pos"), "fantasy_positions": [row.get("pos")], "team": row.get("team"),
                        "status": row.get("bye_or_status") or "Active", "active": True,
                        "injury_status": row.get("injury_status"), "injury_body_part": row.get("injury_body_part"),
                        "depth_chart_order": row.get("depth_chart_order"), "years_exp": 3, "age": 26, "search_rank": 400}
    # a few injury details so the diff has something to show
    players["5947"].update({"injury_status": "Questionable", "injury_body_part": "Hamstring",
                            "injury_start_date": "2026-09-14", "injury_notes": "Limited in practice Wednesday.",
                            "practice_participation": "Limited", "practice_description": "Limited Participation in Practice",
                            "news_updated": 1758100000000})
    players["5849"].update({"injury_status": "Questionable", "injury_body_part": "Ankle",
                            "practice_participation": "DNP", "news_updated": 1758050000000})
    players["9753"].update({"injury_status": "PUP", "injury_body_part": "Knee", "status": "Reserve/PUP"})
    write(out, "/v1/players/nfl", players)

    # ---- state, league, users, rosters
    week_now = {"wednesday": 2, "sunday": 2, "monday": 2, "tuesday": 3}[scenario]
    state = {"week": week_now, "leg": week_now, "season": "2026", "season_type": "regular", "league_season": "2026",
             "previous_season": "2025", "season_start_date": "2026-09-09", "display_week": week_now,
             "league_create_season": "2026", "season_has_scores": True}
    write(out, "/v1/state/nfl", state)
    league = {"name": "Pretend Sportsball League '26", "season": "2026", "status": "in_season", "league_id": LEAGUE_ID,
              "total_rosters": 12, "roster_positions": ROSTER_POSITIONS, "scoring_settings": SCORING,
              "settings": {"waiver_budget": 200, "waiver_clear_days": 2, "waiver_day_of_week": 3, "league_average_match": 1,
                           "playoff_week_start": 15, "playoff_teams": 6, "trade_deadline": 12, "max_keepers": 2,
                           "reserve_slots": 2, "type": 2}}
    write(out, f"/v1/league/{LEAGUE_ID}", league)
    team_names = {t["roster_id"]: t["team"] for t in latest["completed_week"]["league_scoreboard"]}
    display = {8: "Mockstar", 1: "ben_g", 2: "danglish9", 3: "dlamas", 4: "TheRafiBombb", 5: "jnally8", 6: "Breadsticks310",
               7: "marlos9", 9: "cjgordon819", 10: "juicyjuicy100", 11: "aCaps", 12: "espad"}
    users = [{"user_id": f"u{rid}", "display_name": display[rid], "username": None, "metadata": {"team_name": team_names[rid]}}
             for rid in range(1, 13)]
    write(out, f"/v1/league/{LEAGUE_ID}/users", users)

    my_players = [r["player_id"] for r in latest["upcoming_week"]["starters"] + latest["upcoming_week"]["bench"]
                  if r.get("player_id")]
    my_starters = [r["player_id"] for r in latest["upcoming_week"]["starters"]]
    my_ir = [r["player_id"] for r in latest["upcoming_week"]["ir"]]
    taken = set(my_players + my_ir)
    ranked_ids = [r for r in players if r in {(x.get("sleeper_id") or "").replace(".0", "") for x in rank_rows}]
    ranked_ids.sort(key=lambda pid: players[pid].get("search_rank", 999))
    pool_by_pos = {pos: [pid for pid in ranked_ids if players[pid]["position"] == pos and pid not in taken]
                   for pos in ("QB", "RB", "WR", "TE")}
    def_pool = [t for t in TEAMS if t != "SEA"]
    rosters = []
    wk1_scores = {t["roster_id"]: t["actual"] for t in latest["completed_week"]["league_scoreboard"]}
    median = sorted(wk1_scores.values())[5:7]
    median = sum(median) / 2
    for rid in range(1, 13):
        if rid == 8:
            plist, starters, reserve = my_players, my_starters, my_ir
        else:
            starters = [pool_by_pos["QB"].pop(0), pool_by_pos["RB"].pop(0), pool_by_pos["RB"].pop(0),
                        pool_by_pos["WR"].pop(0), pool_by_pos["WR"].pop(0), pool_by_pos["WR"].pop(0),
                        pool_by_pos["RB"].pop(0) if rid % 2 else pool_by_pos["TE"].pop(0), def_pool.pop(0)]
            bench = [pool_by_pos["RB"].pop(0), pool_by_pos["WR"].pop(0), pool_by_pos["WR"].pop(0),
                     pool_by_pos["RB"].pop(0), pool_by_pos["TE"].pop(0), pool_by_pos["QB"].pop(0)]
            plist = starters + bench
            reserve = []
        opp_rid = next(t["roster_id"] for t in latest["completed_week"]["league_scoreboard"]
                       if t["matchup_id"] == next(x["matchup_id"] for x in latest["completed_week"]["league_scoreboard"]
                                                  if x["roster_id"] == rid) and t["roster_id"] != rid)
        wins = int(wk1_scores[rid] > wk1_scores[opp_rid]) + int(wk1_scores[rid] > median)
        rosters.append({"roster_id": rid, "owner_id": f"u{rid}", "league_id": LEAGUE_ID, "players": plist + reserve,
                        "starters": starters, "reserve": reserve, "taxi": None,
                        "settings": {"wins": wins, "losses": 2 - wins, "ties": 0, "fpts": int(wk1_scores[rid]),
                                     "fpts_decimal": int(round((wk1_scores[rid] % 1) * 100)),
                                     "fpts_against": int(wk1_scores[opp_rid]), "waiver_budget_used": 0,
                                     "waiver_position": rid, "total_moves": 0}})
    write(out, f"/v1/league/{LEAGUE_ID}/rosters", rosters)

    # ---- projections and stats
    rank_by_id = {}
    for r in rank_rows:
        sid = (r.get("sleeper_id") or "").strip()
        if sid.endswith(".0"):
            sid = sid[:-2]
        if sid:
            rank_by_id[sid] = r
    def_ppg = {r["team"]: float(r["wtd_def_ppg"]) for r in def_rows}
    real_proj = {}
    real_act = {}
    for row in latest["completed_week"]["starters"] + latest["completed_week"]["bench"]:
        real_proj[(row["player_id"], 1)] = row.get("projected")
        real_act[row["player_id"]] = row.get("actual")
    for row in latest["upcoming_week"]["starters"] + latest["upcoming_week"]["bench"] + latest["upcoming_week"]["ir"]:
        if row.get("player_id"):
            real_proj[(row["player_id"], 2)] = row.get("projected")
    for pos_rows in latest["waivers_by_position"].values():
        for row in pos_rows:
            real_proj[(row["player_id"], 2)] = row.get("proj_next_week")
            real_proj[(row["player_id"], 1)] = row.get("projected_week_1")
            real_act[row["player_id"]] = row.get("actual_week_1")

    def base_pts(pid, pos):
        if pos == "DEF":
            return def_ppg.get(pid, 6.0)
        r = rank_by_id.get(pid)
        if r and r.get("proj_ppg"):
            return float(r["proj_ppg"])
        return 4.0

    def proj_rows(week):
        rows = []
        for pid, p in players.items():
            pos = p["position"]
            team = p.get("team")
            if pos not in ("QB", "RB", "WR", "TE", "DEF") or not team:
                continue
            gd = game_date.get((team, week))
            if not gd or gd[1] == "BYE":
                continue
            pts = real_proj.get((pid, week))
            if pts is None:
                pts = base_pts(pid, pos) * random.uniform(0.85, 1.15)
            if p.get("injury_status") in ("Out", "IR", "PUP"):
                pts = 0.0
            rows.append({"player_id": pid, "team": team, "opponent": gd[1], "date": gd[0], "week": week,
                         "season": "2026", "season_type": "regular", "sport": "nfl", "category": "proj",
                         "stats": statline_for(pos, pts), "last_modified": 1758000000000})
        return rows

    def stat_rows(week, only_teams=None):
        rows = []
        for pid, p in players.items():
            pos = p["position"]
            team = p.get("team")
            if pos not in ("QB", "RB", "WR", "TE", "DEF") or not team:
                continue
            gd = game_date.get((team, week))
            if not gd or gd[1] == "BYE":
                continue
            if only_teams is not None and team not in only_teams:
                continue
            if week == 1 and pid in real_act and real_act[pid] is not None:
                pts = real_act[pid]
            else:
                pts = max(0.0, random.gauss(base_pts(pid, pos), 5.0))
            st = statline_for(pos, pts)
            st["gp"] = 1
            if pos == "DEF":
                st["def_3_and_out"] = random.randint(1, 4)
                st["def_4_and_stop"] = random.randint(0, 2)
            rows.append({"player_id": pid, "team": team, "opponent": gd[1], "date": gd[0], "week": week,
                         "season": "2026", "season_type": "regular", "sport": "nfl", "category": "stat", "stats": st})
        return rows

    qs = "position[]=QB&position[]=RB&position[]=WR&position[]=TE&position[]=DEF"
    for wk in (1, 2, 3):
        write(out, f"/projections/nfl/2026/{wk}?season_type=regular&{qs}", proj_rows(wk))
    write(out, f"/stats/nfl/2026/1?season_type=regular&{qs}", stat_rows(1))
    if scenario == "wednesday":
        write(out, f"/stats/nfl/2026/2?season_type=regular&{qs}", [])
    elif scenario == "sunday":
        # Thursday game done (week 2: which teams played Thursday? use the schedule's earliest date)
        thu = min(gd[0] for (t, w), gd in game_date.items() if w == 2 and gd[1] != "BYE")
        thu_teams = {t for (t, w), gd in game_date.items() if w == 2 and gd[0] == thu}
        write(out, f"/stats/nfl/2026/2?season_type=regular&{qs}", stat_rows(2, thu_teams))
    else:
        write(out, f"/stats/nfl/2026/2?season_type=regular&{qs}", stat_rows(2))
    write(out, f"/stats/nfl/2026/3?season_type=regular&{qs}", [])

    # ---- matchups (weeks 1-17 pairings; points for week 1 only)
    pairs_w1 = {t["roster_id"]: t["matchup_id"] for t in latest["completed_week"]["league_scoreboard"]}
    wk1_proj = {}
    for wk in range(1, 18):
        rows = []
        for r in rosters:
            rid = r["roster_id"]
            mid = pairs_w1[rid] if wk == 1 else ((rid + wk) % 6) + 1
            row = {"roster_id": rid, "matchup_id": mid, "players": r["players"], "starters": r["starters"],
                   "points": 0, "players_points": {}, "starters_points": [], "custom_points": None}
            if wk == 1:
                row["points"] = wk1_scores[rid]
                if rid == 8:
                    row["players_points"] = {x["player_id"]: x["actual"] for x in
                                             latest["completed_week"]["starters"] + latest["completed_week"]["bench"]}
                    row["starters"] = [x["player_id"] for x in latest["completed_week"]["starters"]]
                else:
                    pts = {pid: round(max(0.0, random.gauss(base_pts(pid, players[pid]["position"]), 5)), 2)
                           for pid in r["players"]}
                    scale = wk1_scores[rid] / max(1.0, sum(pts[s] for s in r["starters"]))
                    row["players_points"] = {k: round(v * scale, 2) for k, v in pts.items()}
                row["starters_points"] = [row["players_points"].get(s, 0) for s in row["starters"]]
            elif wk == 2 and scenario in ("monday", "tuesday"):
                row["points"] = round(random.uniform(80, 140), 2)
            rows.append(row)
        write(out, f"/v1/league/{LEAGUE_ID}/matchups/{wk}", rows)
    # ---- transactions: one drop 1 day ago, one 4 days ago
    tx = [{"transaction_id": "t1", "type": "free_agent", "status": "complete", "roster_ids": [3], "adds": {"11370": 3},
           "drops": {"7049": 3}, "settings": None, "created": 1758150000000, "status_updated": 1758150000000, "leg": 2,
           "creator": "u3"}]
    for wk in range(1, 5):
        write(out, f"/v1/league/{LEAGUE_ID}/transactions/{wk}", tx if wk == 2 else [])
    write(out, "/v1/players/nfl/trending/add?lookback_hours=72&limit=100",
          [{"player_id": r["player_id"], "count": r["trending_adds_72h"]} for r in latest["waivers_trending"][:60]])
    print(f"fixtures written to {out} ({scenario}): {len(players)} players")


if __name__ == "__main__":
    main()
