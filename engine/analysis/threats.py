"""Competitor threat per waiver target: which teams are most likely to bid, with their FAAB left and
why. A plain point score, every point tied to a sentence the dashboard prints. [Guessing] on the
weights; they only order the list, they never change a projection.

  +4   owns an absent (Out, Doubtful, IR, inactive) player at the target's position on the same NFL team
       (the natural replacement bidder: Amateur Hour owns De'Von Achane, so they want Ollie Gordon)
  +1.5 owns a Questionable player at that position on the same NFL team
  +1   owns the healthy lead player at that position on the same NFL team (handcuff interest)
  +2   one of their starters at the position is Out, Doubtful or on IR; +1 if Questionable
  +2   a starter at the position picked up an Out/IR tag in the last 7 days (lost a starter), when
       that player is not already counted above
  +1   dropped a player at the position in the last 7 days
  +1   a starter at the position is on bye next week
  +1   healthy players at the position no more than the starting slots for it (thin; not used for DEF)
  +0.5 has bid on the position this season
Teams with no FAAB left are skipped; Aaron's own team is never listed.
"""
ABSENT = {"Out", "Doubtful", "IR", "PUP", "Sus", "NA", "DNR", "COV"}
NEED = {"QB": 1, "RB": 2, "WR": 2, "TE": 0, "DEF": 0}   # every team carries one DEF, so "thin" says nothing there
MIN_SCORE = 1.0
TOP_N = 3


def score_team(team, target):
    """team: {"roster_id", "team", "remaining", "players": [{"player_id","name","pos","nfl","status",
    "starter","bye_next","lead"}], "newly_out": [names], "dropped_recent": [names], "bid_positions": set}.
    target: {"player_id","name","pos","team"}. Returns (score, reasons)."""
    pos, nfl = target["pos"], target.get("team")
    score, why = 0.0, []
    same = [p for p in team["players"] if p["pos"] == pos and nfl and p.get("nfl") == nfl and p["player_id"] != target["player_id"]]
    for p in same:
        if p.get("status") in ABSENT:
            score += 4
            why.append(f"owns {p['name']} ({p['status']}), the {nfl} {pos} he would replace")
        elif p.get("status") == "Questionable":
            score += 1.5
            why.append(f"owns {p['name']} (Questionable), a {nfl} {pos} he could replace")
        elif p.get("lead"):
            score += 1
            why.append(f"owns {p['name']}, the {nfl} {pos}1 (handcuff interest)")
    cited = {p["player_id"] for p in same if p.get("status") in ABSENT or p.get("status") == "Questionable"}
    starters = [p for p in team["players"] if p["pos"] == pos and p.get("starter")]
    hurt = [p for p in starters if p.get("status") in ABSENT and p["player_id"] not in cited]
    q = [p for p in starters if p.get("status") == "Questionable" and p["player_id"] not in cited]
    if hurt:
        score += 2
        why.append("starter " + ", ".join(f"{p['name']} {p['status']}" for p in hurt))
    elif q:
        score += 1
        why.append("starter " + ", ".join(f"{p['name']} Questionable" for p in q))
    counted = {p["name"] for p in same + hurt + q}
    newly = [n for n in team.get("newly_out") or [] if n.rsplit(" (", 1)[0] not in counted]
    if newly:
        score += 2
        why.append("starter ruled out or put on IR this week: " + ", ".join(newly))
    if team.get("dropped_recent"):
        score += 1
        why.append("just dropped " + ", ".join(team["dropped_recent"]))
    byes = [p for p in starters if p.get("bye_next")]
    if byes:
        score += 1
        why.append("bye next week for " + ", ".join(p["name"] for p in byes))
    healthy = [p for p in team["players"] if p["pos"] == pos and p.get("status") not in ABSENT]
    if NEED.get(pos, 0) and len(healthy) <= NEED[pos]:
        score += 1
        why.append(f"only {len(healthy)} healthy {pos}{'s' if len(healthy) != 1 else ''}")
    if pos in (team.get("bid_positions") or set()):
        score += 0.5
        why.append(f"has bid on a {pos} before")
    return score, why


def likely_bidders(teams, target, my_rid, top_n=TOP_N):
    out = []
    for t in teams:
        if t["roster_id"] == my_rid or (t.get("remaining") is not None and t["remaining"] <= 0):
            continue
        s, why = score_team(t, target)
        if s >= MIN_SCORE:
            out.append({"roster_id": t["roster_id"], "team": t["team"], "remaining": t.get("remaining"),
                        "score": s, "why": why, "usual_bid": t.get("usual_bid"), "repeated": t.get("repeated") or [],
                        "pos_max": (t.get("pos_bids") or {}).get(target["pos"])})
    out.sort(key=lambda b: (-b["score"], -(b["remaining"] or 0), b["team"]))
    return out[:top_n]


def team_states(ctx, market_teams, market_rows, week_next):
    """Adapter: one plain dict per team from the committed data, for score_team."""
    from .vacated import is_absent
    fin = {t["roster_id"]: t for t in market_teams}
    bid_pos, pos_bids = {}, {}
    for r in market_rows:
        filed = ([(r["winner_rid"], r["winning_bid"])] if r["winner_rid"] is not None else []) +                 [(lb["roster_id"], lb["bid"]) for lb in r["losing"]]
        for rid, bid in filed:
            if r["pos"]:
                bid_pos.setdefault(rid, set()).add(r["pos"])
                cur = pos_bids.setdefault(rid, {}).get(r["pos"])
                pos_bids[rid][r["pos"]] = max(bid or 0, cur or 0)
    # who picked up an Out/IR tag in the last 7 days, from the daily injury diffs
    latest = {}   # (roster_id, pos, name) -> newest Out/IR-type status, oldest diff first so the last write wins
    for d in ctx.injury_diffs[-7:]:
        for c in d.get("changes") or []:
            to = ((c.get("fields") or {}).get("injury_status") or {}).get("to")
            if to in ("Out", "IR", "Doubtful", "PUP") and c.get("slot") not in ("BN", "IR", None):
                latest[(c.get("roster_id"), c.get("pos"), c["name"])] = to
    newly = {}
    for (rid, pos, name), to in latest.items():
        newly.setdefault(rid, {}).setdefault(pos, set()).add(f"{name} ({to})")
    cutoff = ctx.now.timestamp() * 1000 - 7 * 86400 * 1000
    dropped = {}
    for rows in (ctx.transactions or {}).values():
        for t in rows or []:
            if t.get("status") != "complete" or (t.get("status_updated") or 0) < cutoff:
                continue
            for pid, rid in (t.get("drops") or {}).items():
                dropped.setdefault(rid, []).append(pid)
    # lead player per NFL team and position: the depth chart's number 1
    lead = set()
    for pid, p in ctx.players.items():
        if p.get("depth_chart_order") == 1 and p.get("team"):
            lead.add(pid)
    out = []
    for r in ctx.rosters:
        rid = r["roster_id"]
        starters = {s for s in r.get("starters") or [] if s and s != "0"}
        players = []
        for pid in set((r.get("players") or []) + (r.get("reserve") or [])):
            info = ctx.info(pid)
            inj = ctx.injury(pid) or {}
            status = inj.get("injury_status")
            if not status and is_absent(None, (ctx.players.get(pid) or {}).get("status")):
                status = "IR" if pid in (r.get("reserve") or []) else "Out"
            players.append({"player_id": pid, "name": info["name"], "pos": info["pos"], "nfl": info["team"],
                            "status": status, "starter": pid in starters, "lead": pid in lead,
                            "bye_next": bool(info["team"]) and ctx.bye_week(info["team"]) == week_next})
        f = fin.get(rid) or {}
        out.append({"roster_id": rid, "team": ctx.team_name(rid), "remaining": f.get("remaining"),
                    "usual_bid": f.get("usual_bid"), "repeated": f.get("repeated") or [],
                    "players": players, "bid_positions": bid_pos.get(rid, set()), "pos_bids": pos_bids.get(rid, {}),
                    "_newly": newly.get(rid, {}), "_dropped": dropped.get(rid, [])})
    return out


def for_target(states, target, my_rid, info):
    """Fill the per-position fields (newly out, dropped) for this target's position, then rank."""
    pos = target["pos"]
    teams = []
    for s in states:
        t = dict(s)
        t["newly_out"] = sorted((s.get("_newly") or {}).get(pos, set()))
        t["dropped_recent"] = [info(p)["name"] for p in s.get("_dropped") or [] if info(p)["pos"] == pos]
        teams.append(t)
    return likely_bidders(teams, target, my_rid)
