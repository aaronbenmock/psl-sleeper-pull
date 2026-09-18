"""Keeper valuation for late-season waiver and trade decisions (stretch item 1).

For each player on Aaron's roster:
  projected_2027_ppg = rest-of-season value (preseason model blended toward the season average),
                       aged: RB minus 8% per year past 27, WR/TE minus 5% past 30, QB minus 4% past 34
                       [Guessing on the aging rates; standard fantasy rules of thumb]
  cost_round         = the round he was drafted in 2026 (waiver adds: round 14) under the
                       assumed keeper rule in reference/draft_2026_mockstar.json
  slot_baseline_ppg  = what a pick in that round normally returns: the preseason proj_ppg of the
                       players ranked around that overall pick (rank = 12 x (round - 1) + 3),
                       averaged over the 6 nearest, by the position he plays
  keeper_surplus     = projected_2027_ppg minus slot_baseline_ppg
The two largest surpluses are the keeper candidates. A positive surplus on a player Aaron is
not going to keep is trade value: another manager might keep him.
"""
import json
import os

from .. import config, store
from .recommend import ros_value

AGE_RULES = {"RB": (27, 0.08), "WR": (30, 0.05), "TE": (30, 0.05), "QB": (34, 0.04)}


def _slot_baseline(ctx, pos, round_no):
    rank = 12 * (round_no - 1) + 3
    rows = [r for r in ctx.rankings.values() if r.get("pos_2026") == pos and r.get("suggested_rank")]
    if not rows:
        return None
    rows.sort(key=lambda r: abs(r["suggested_rank"] - rank))
    near = [r["proj_ppg"] for r in rows[:6] if r.get("proj_ppg") is not None]
    return round(sum(near) / len(near), 2) if near else None


def build(ctx, lineup_rec):
    path = os.path.join(config.REFERENCE_DIR, "draft_2026_mockstar.json")
    draft = store.read_json(path, {}) or {}
    picks = draft.get("picks") or {}
    undrafted = int(draft.get("undrafted_cost_round") or 14)
    week = ctx.upcoming_week
    rows = []
    for r in lineup_rec["lineup"] + lineup_rec["bench"] + lineup_rec["ir"]:
        pid = r.get("player_id")
        if not pid:
            continue
        pos, team = r["pos"], r["team"]
        ros, how = ros_value(ctx, pid, week, r.get("sleeper"))
        p = ctx.players.get(pid) or ctx.fallback_players.get(pid) or {}
        pre = ctx.preseason(pid, pos, team) or {}
        age = p.get("age") or pre.get("age")
        years = p.get("years_exp") if p.get("years_exp") is not None else pre.get("years_exp")
        proj_2027 = ros
        age_note = ""
        if pos in AGE_RULES and age:
            cliff, rate = AGE_RULES[pos]
            over = max(0, (age + 1) - cliff)
            if over:
                proj_2027 = ros * (1 - rate) ** over
                age_note = f"aged {int(rate * 100)}%/yr for {over} yr past {cliff}"
        if pos == "DEF":
            proj_2027 = ros * 0.85
            age_note = "DEF year-to-year is weak; 15% haircut"
        pk = picks.get(pid) or {}
        round_no = pk.get("round") or undrafted
        base = _slot_baseline(ctx, pos, round_no) if pos != "DEF" else (ctx.def_rankings.get(team) or {}).get("wtd_def_ppg")
        if pos == "DEF" and base is not None:
            base = round(base * 0.7, 2)  # a DEF at round 8 is replaceable; most of its value is not surplus
        surplus = round(proj_2027 - base, 2) if base is not None else None
        rows.append({"player_id": pid, "name": r["name"], "pos": pos, "team": team, "age": age, "years_exp": years,
                     "ros": round(ros, 2), "ros_how": how, "proj_2027": round(proj_2027, 2), "age_note": age_note,
                     "cost_round": round_no, "cost_pick": pk.get("pick") or f"undrafted (round {undrafted} assumed)",
                     "slot_baseline": base, "surplus": surplus, "kept_2026": bool(pk.get("kept_2026"))})
    rows.sort(key=lambda x: -(x["surplus"] if x["surplus"] is not None else -99))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
        r["why"] = (f"Worth about {r['proj_2027']:.1f} a week next year ({r['ros_how']}"
                    + (f", {r['age_note']}" if r["age_note"] else "") + f"); a round-{r['cost_round']} pick usually returns "
                    + (f"{r['slot_baseline']:.1f}" if r["slot_baseline"] is not None else "n/a")
                    + f" at {r['pos']}, so keeping him is worth {r['surplus']:+.1f} a week." if r["surplus"] is not None else "no baseline available.")
    notes = [
        "Keeper cost rule is assumed (same round as drafted; undrafted adds cost round 14). Fix reference/draft_2026_mockstar.json if the league rule differs. [Guessing]",
        f"Max keepers {draft.get('max_keepers', 2)}. Josh Allen used one slot in 2026 at 2.10.",
        "Surplus is next year's expected weekly points above what that draft slot normally buys. It moves every week as season averages accumulate; read it seriously from about week 8.",
        "Trade angle: a player with positive surplus you will not keep is worth more to a manager who would, before the week 12 deadline.",
    ]
    return {"week": week, "rows": rows, "top2": [r["name"] for r in rows[:2] if r["surplus"] is not None], "notes": notes,
            "rule": draft.get("keeper_cost_rule")}
