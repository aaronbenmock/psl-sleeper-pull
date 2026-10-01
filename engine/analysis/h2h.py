"""Head-to-head opponent for the upcoming week, on the Lineup tab.

Both sides are valued with the same blend Aaron's own lineup uses (recommend.value_player), so the
comparison is like for like. The opponent is shown twice: the lineup he has set in Sleeper now, and
the best lineup his roster allows (max points, the same greedy fill), because managers set lineups
late. Favored = Aaron's recommended total beats the opponent's set lineup by more than TOSS_UP.
Because this league also plays the league median every week, Aaron's total is compared with the
median of all twelve teams' projected totals as well.
"""
import statistics

from .recommend import value_player, build_lineup, freshest_projections

TOSS_UP = 5.0      # [Guessing]: inside this margin the game is called a toss-up
INJ_SHOW = {"Questionable", "Doubtful", "Out", "IR", "PUP", "Sus"}


def opponent_rid(matchups, my_rid):
    me = next((m for m in matchups or [] if m.get("roster_id") == my_rid), None)
    if not me or me.get("matchup_id") is None:
        return None
    opp = next((m for m in matchups if m.get("matchup_id") == me["matchup_id"] and m.get("roster_id") != my_rid), None)
    return opp.get("roster_id") if opp else None


def verdict(mine, theirs):
    if mine is None or theirs is None:
        return "unknown", None
    margin = round(mine - theirs, 1)
    if margin > TOSS_UP:
        return "favored", margin
    if margin < -TOSS_UP:
        return "underdog", margin
    return "toss-up", margin


def valued(ctx, pid, week, proj):
    """value_player, except a player the committed data has no projection row for at all (other
    teams' players before Thursday's first snapshot) is valued at his baseline x injury multiplier
    instead of zero, and flagged. A row that exists with 0 still means Sleeper ruled him out."""
    v = value_player(ctx, pid, week, proj.get(pid))
    if pid not in proj and not v["bye"] and v.get("baseline") is not None and v["inj_mult"] > 0:
        v = dict(v, expected=round(v["baseline"] * v["inj_mult"], 2), playing=True, baseline_only=True)
    return v


def team_total(ctx, roster, week, proj):
    """(set-lineup total, best-lineup total, valued starter rows, injured starters)."""
    reserve = set(roster.get("reserve") or [])
    active = [p for p in roster.get("players") or [] if p not in reserve]
    vals = {p: valued(ctx, p, week, proj) for p in active}
    starters = [s for s in roster.get("starters") or [] if s and s != "0"]
    set_rows = [vals.get(s) or valued(ctx, s, week, proj) for s in starters]
    set_total = round(sum(r["expected"] or 0 for r in set_rows), 1)
    best, _ = build_lineup(list(vals.values()), ctx.slots)
    best_total = round(sum(r.get("expected") or 0 for r in best), 1)
    hurt = [{"name": r["name"], "pos": r["pos"], "status": r["injury_status"], "expected": r["expected"],
             "body": r.get("injury_body_part")}
            for r in set_rows if r.get("injury_status") in INJ_SHOW or (not r["playing"] and not r["bye"])]
    n_base = sum(1 for r in set_rows if r.get("baseline_only"))
    byes = [r["name"] for r in set_rows if r.get("bye")]
    return set_total, best_total, set_rows, hurt, byes, n_base


def build(ctx, lineup_rec):
    week = ctx.upcoming_week
    rows = ctx.matchups.get(week) or []
    rid = opponent_rid(rows, ctx.my_rid)
    out = {"week": week, "available": False, "median_game": ctx.settings.get("league_average_match") == 1}
    if rid is None:
        out["reason"] = f"no week {week} pairing in data/league/matchups yet"
        return out
    proj, src = freshest_projections(ctx, week, prefer_snapshot=True)
    opp_roster = next((r for r in ctx.rosters if r.get("roster_id") == rid), None)
    if not opp_roster:
        out["reason"] = "opponent roster not in rosters.json"
        return out
    set_total, best_total, set_rows, hurt, byes, n_base = team_total(ctx, opp_roster, week, proj)
    mine = lineup_rec.get("expected_total")
    v, margin = verdict(mine, set_total)
    # median game: every team's set lineup on the same blend
    totals = {}
    for r in ctx.rosters:
        if r.get("roster_id") == ctx.my_rid:
            continue
        totals[r["roster_id"]] = team_total(ctx, r, week, proj)[0]
    med = round(statistics.median(totals.values()), 1) if totals else None
    mv, mmargin = verdict(mine, med)
    out.update({
        "available": True, "opponent": ctx.team_name(rid), "manager": ctx.manager_name(rid), "roster_id": rid,
        "my_total": mine, "opp_set_total": set_total, "opp_best_total": best_total,
        "verdict": v, "margin": margin, "verdict_vs_best": verdict(mine, best_total)[0],
        "opp_injured": hurt, "opp_byes": byes,
        "opp_starters": [{"name": r["name"], "pos": r["pos"], "expected": r["expected"], "injury_status": r["injury_status"],
                          "baseline_only": bool(r.get("baseline_only"))}
                         for r in set_rows],
        "median_total": med, "median_verdict": mv, "median_margin": mmargin,
        "source": src, "opp_baseline_only": n_base,
        "why": (f"Your recommended lineup projects {mine:.1f}; {ctx.team_name(rid)}'s set lineup {set_total:.1f} "
                f"(best possible from their roster {best_total:.1f}). Margin {margin:+.1f}: {v}"
                + (f", with a {TOSS_UP:g}-point band called a toss-up" if v == "toss-up" else "") + ".") if mine is not None else "",
        "note": ("Both sides use the engine blend (0.65 x Sleeper + 0.35 x baseline, injury multipliers)"
                 + (", so the totals are comparable. " if not n_base else ". ") + f"Inside +/-{TOSS_UP:g} points the game is called a toss-up [Guessing]. Your own lineup still "
                 "follows max expected points; the matchup does not change who you start.")
                + (f" {n_base} of their {len(set_rows)} starters have no Sleeper projection in the committed data yet (it covers "
                   "only your roster and the waiver wire until Thursday's first pre-kickoff snapshot), so they are valued at "
                   "their baseline." if n_base else ""),
    })
    return out
