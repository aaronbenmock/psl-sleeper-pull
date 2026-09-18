"""Start/sit and waiver recommendations for Aaron's roster. Every recommendation carries a
plain-English why line with the number that drove it.

Weekly expected points for a player (see docs/METHOD.md):
  baseline = (n x season_avg + 4 x preseason_ppg) / (n + 4)      preseason fades as weeks accumulate
  expected = 0.65 x sleeper_projection + 0.35 x baseline          sleeper carries matchup and injury news
  then an injury multiplier: Questionable 0.90, Doubtful 0.40, Out/IR/PUP/Suspended 0.
Sleeper zeroes the projection of a player who is ruled out, so a 0 projection off a bye is
treated as "not playing".
"""
import os

from .. import config, store
from ..timeutil import parse_iso, iso, to_central

INJ_MULT = {"Questionable": 0.90, "Doubtful": 0.40, "Out": 0.0, "IR": 0.0, "PUP": 0.0, "Sus": 0.0,
            "NA": 0.0, "COV": 0.0, "DNR": 0.0}
W_SLEEPER = 0.65
PRIOR_GAMES = 4
FLEX_ELIGIBLE = {"RB", "WR", "TE"}


def _r(v, n=1):
    return None if v is None else round(v, n)


def freshest_projections(ctx, week, prefer_snapshot=False):
    """Week projections for everyone we know about: the newest snapshot of that week when it is
    newer than latest.json, otherwise latest.json's own rows. Returns (dict pid->pts, source dict)."""
    latest_t = parse_iso(ctx.meta.get("pulled_at_utc"))
    snaps = [s for s in ctx.snap_index if s.get("week") == week]
    proj, src = {}, {"kind": "latest.json", "taken_at_utc": ctx.meta.get("pulled_at_utc")}
    up = ctx.latest.get("upcoming_week") or {}
    if up.get("week") == week:
        for row in (up.get("starters") or []) + (up.get("bench") or []) + (up.get("ir") or []):
            if row.get("player_id"):
                proj[row["player_id"]] = {"p": row.get("projected"), "opp": row.get("opponent"), "bye": row.get("on_bye")}
        for rows in (ctx.latest.get("waivers_by_position") or {}).values():
            for row in rows:
                proj[row["player_id"]] = {"p": row.get("proj_next_week"), "opp": row.get("opponent_next_week"), "bye": None}
    if snaps:
        newest = snaps[-1]
        t = parse_iso(newest.get("taken_at_utc"))
        if t and (prefer_snapshot or not latest_t or t > latest_t):
            snap = store.read_json(os.path.join(ctx.data_dir, *newest["path"].replace("data/", "", 1).split("/")), {})
            if snap and snap.get("players"):
                for pid, row in snap["players"].items():
                    proj[pid] = {"p": row.get("p"), "opp": row.get("opp"), "bye": False, "started": row.get("started"),
                                 "actual": row.get("a")}
                src = {"kind": "pre-kickoff snapshot", "taken_at_utc": newest.get("taken_at_utc"),
                       "label": newest.get("label")}
    return proj, src


def value_player(ctx, pid, week, proj_row, injury=None):
    info = ctx.info(pid)
    pos, team = info["pos"], info["team"]
    sleeper = proj_row.get("p") if proj_row else None
    pre = ctx.preseason_ppg(pid, pos, team)
    avg, n = ctx.season_avg(pid, before_week=week)
    baseline = None
    if pre is not None and avg is not None:
        baseline = (n * avg + PRIOR_GAMES * pre) / (n + PRIOR_GAMES)
    elif pre is not None:
        baseline = pre
    elif avg is not None:
        baseline = avg
    bye = ctx.bye_week(team) == week if team else False
    inj = injury or ctx.injury(pid)
    status = inj.get("injury_status") if inj else None
    mult = INJ_MULT.get(status, 1.0) if status else 1.0
    playing = not bye and sleeper is not None and sleeper > 0
    if not playing:
        expected = 0.0
    elif baseline is not None:
        expected = (W_SLEEPER * sleeper + (1 - W_SLEEPER) * baseline) * mult
    else:
        expected = sleeper * mult
    pre_row = ctx.preseason(pid, pos, team) or {}
    return {
        "player_id": pid, "name": info["name"], "pos": pos, "team": team, "opp": (proj_row or {}).get("opp"),
        "sleeper": _r(sleeper, 2), "preseason": _r(pre, 2), "season_avg": _r(avg, 2), "n_games": n,
        "baseline": _r(baseline, 2), "expected": _r(expected, 2), "injury_status": status,
        "injury_body_part": inj.get("injury_body_part") if inj else None,
        "practice": inj.get("practice_participation") if inj else None,
        "bye": bye, "playing": playing, "inj_mult": mult,
        "boom_rate": pre_row.get("boom_rate"), "sd_wk": pre_row.get("sd_wk"), "vor": pre_row.get("vor"),
        "started": (proj_row or {}).get("started"), "actual_so_far": (proj_row or {}).get("actual"),
    }


def _why_value(v):
    bits = []
    if not v["playing"]:
        if v["bye"]:
            return f"On bye week, 0 points."
        if v["injury_status"] in INJ_MULT and INJ_MULT[v["injury_status"]] == 0:
            return f"Ruled {v['injury_status']}, 0 points."
        return "No Sleeper projection this week (ruled out or not active), 0 points."
    bits.append(f"Sleeper projects {v['sleeper']:.1f}")
    if v["baseline"] is not None:
        if v["n_games"]:
            bits.append(f"season average {v['season_avg']:.1f} over {v['n_games']} game{'s' if v['n_games'] != 1 else ''}")
        if v["preseason"] is not None:
            bits.append(f"preseason model {v['preseason']:.1f}")
    if v["injury_status"] and v["inj_mult"] < 1:
        bits.append(f"{v['injury_status']} ({v['injury_body_part'] or 'unspecified'}) cuts it by {int((1 - v['inj_mult']) * 100)}%")
    s = ", ".join(bits) + f". Blended expectation {v['expected']:.1f}"
    if v["opp"]:
        s += f" vs {v['opp']}"
    return s + "."


def build_lineup(values, slots):
    """Greedy fill by expected points. Returns (lineup rows with slot, bench rows)."""
    pool = sorted(values, key=lambda v: -(v["expected"] or 0))
    used = set()
    lineup = []
    for slot in slots:
        elig = FLEX_ELIGIBLE if slot == "FLEX" else {slot}
        pick = next((v for v in pool if v["player_id"] not in used and v["pos"] in elig), None)
        if pick:
            used.add(pick["player_id"])
            lineup.append(dict(pick, slot=slot))
        else:
            lineup.append({"slot": slot, "name": "EMPTY", "expected": 0.0, "player_id": None, "pos": slot})
    bench = [dict(v, slot="BN") for v in pool if v["player_id"] not in used]
    return lineup, bench


def lineup_recommendation(ctx):
    week = ctx.upcoming_week
    proj, src = freshest_projections(ctx, week)
    roster = ctx.my_roster or {}
    up = ctx.latest.get("upcoming_week") or {}
    if roster.get("players"):
        active = [p for p in roster["players"] if p not in (roster.get("reserve") or [])]
        reserve = roster.get("reserve") or []
        current = roster.get("starters") or []
    else:
        active = [r["player_id"] for r in (up.get("starters") or []) + (up.get("bench") or []) if r.get("player_id")]
        reserve = [r["player_id"] for r in up.get("ir") or [] if r.get("player_id")]
        current = [r.get("player_id") for r in up.get("starters") or []]
    values = [value_player(ctx, pid, week, proj.get(pid)) for pid in active]
    lineup, bench = build_lineup(values, ctx.slots)
    for row in lineup + bench:
        if row.get("player_id"):
            row["why"] = _why_value(row)
    by_id = {v["player_id"]: v for v in values}
    changes = []
    cur_set = [p for p in current if p and p != "0"]
    rec_set = [r["player_id"] for r in lineup if r.get("player_id")]
    outs = [p for p in cur_set if p not in rec_set]
    ins = [p for p in rec_set if p not in cur_set]
    for o, i in zip(outs, ins):
        vo, vi = by_id.get(o), by_id.get(i)
        if vo and vi:
            changes.append({"out": vo["name"], "in": vi["name"], "out_expected": vo["expected"], "in_expected": vi["expected"],
                            "why": f"{vi['name']} {vi['expected']:.1f} vs {vo['name']} {vo['expected']:.1f} expected "
                                   f"({vi['expected'] - vo['expected']:+.1f}). " + (vo["why"] if not vo["playing"] else "")})
    for i in ins[len(outs):]:
        vi = by_id.get(i)
        if vi:
            changes.append({"out": "(empty slot)", "in": vi["name"], "out_expected": 0, "in_expected": vi["expected"],
                            "why": f"Slot was empty; {vi['name']} adds {vi['expected']:.1f}."})
    close = []
    for row in lineup:
        if not row.get("player_id"):
            continue
        elig = FLEX_ELIGIBLE if row["slot"] == "FLEX" else {row["slot"]}
        for b in bench:
            if b["pos"] in elig and b["playing"] and row["expected"] - b["expected"] < 1.5:
                tie = ""
                if row.get("boom_rate") is not None and b.get("boom_rate") is not None:
                    hi = row if row["boom_rate"] >= b["boom_rate"] else b
                    tie = (f" Tiebreak: {hi['name']} has the higher ceiling "
                           f"(boom rate {hi['boom_rate'] * 100:.0f}% vs {min(row['boom_rate'], b['boom_rate']) * 100:.0f}%).")
                close.append({"slot": row["slot"], "starter": row["name"], "bench": b["name"],
                              "gap": _r(row["expected"] - b["expected"], 1),
                              "why": f"{row['name']} {row['expected']:.1f} vs {b['name']} {b['expected']:.1f}, "
                                     f"only {row['expected'] - b['expected']:.1f} apart.{tie}"})
    ir_rows = [dict(value_player(ctx, pid, week, proj.get(pid)), slot="IR") for pid in reserve]
    total = round(sum(r.get("expected") or 0 for r in lineup), 1)
    notes = []
    if src["kind"] == "latest.json":
        age = ctx.data_age_hours()
        notes.append(f"Projections are from the Wednesday pull ({age} hours old). Pre-kickoff snapshots refresh them "
                     f"Thursday evening, Sunday morning and Monday evening.")
    else:
        t = parse_iso(src["taken_at_utc"])
        notes.append(f"Projections are from the {src.get('label', '')} snapshot taken {to_central(t).strftime('%a %b %d %I:%M %p')} Central.")
    played = [r for r in lineup + bench if r.get("started")]
    if played:
        notes.append(f"{len(played)} of your players have already kicked off this week; their rows show points so far.")
    return {"week": week, "generated_at_utc": iso(ctx.now), "source": src, "lineup": lineup, "bench": bench, "ir": ir_rows,
            "current_starters": [by_id.get(p, {}).get("name") or ctx.name(p) for p in cur_set],
            "changes": changes, "close_calls": close, "expected_total": total, "notes": notes,
            "method": f"expected = {W_SLEEPER:.2f} x Sleeper + {1 - W_SLEEPER:.2f} x baseline; baseline = "
                      f"(n x season avg + {PRIOR_GAMES} x preseason) / (n + {PRIOR_GAMES}); injury multipliers Q 0.90, D 0.40, Out 0."}


# ---------------------------------------------------------------- waivers
def ros_value(ctx, pid, week, next_proj):
    """Rest-of-season weekly value: preseason model blended toward the season average, or a
    discounted next-week projection when we have neither."""
    info = ctx.info(pid)
    pre = ctx.preseason_ppg(pid, info["pos"], info["team"])
    avg, n = ctx.season_avg(pid, before_week=week)
    if pre is not None and avg is not None:
        return (n * avg + PRIOR_GAMES * pre) / (n + PRIOR_GAMES), "model+season"
    if pre is not None:
        return pre, "preseason model"
    if avg is not None and n >= 1:
        return (n * avg + PRIOR_GAMES * 0.8 * (next_proj or avg)) / (n + PRIOR_GAMES), "season avg"
    if next_proj:
        return next_proj * 0.8, "next-week projection, discounted 20% (no history)"
    return 0.0, "no data"


def bid_size(gain, weeks_left, trending, budget_left, early_season, max_adds=1):
    """Dollars for a FAAB claim. gain = weekly points gained for your lineup over the player dropped."""
    if gain <= 0.5:
        return 0, "gain under 0.5 points per week, not worth a claim"
    raw = gain * weeks_left * 0.6
    comp = 1 + 0.5 * (min(1.0, (trending or 0) / max(max_adds, 1)) ** 0.5)
    raw *= comp
    if early_season:
        raw *= 1.15
    cap = budget_left * (0.60 if gain >= 5 else 0.45)
    bid = int(round(min(max(raw, 1), cap)))
    why = (f"{gain:.1f} pts/week x {weeks_left} weeks left x $0.60 per point"
           + (f", x{comp:.2f} demand premium ({trending:,} Sleeper adds in 72h; the hottest player on the wire has {max_adds:,})" if comp > 1.01 else "")
           + (", x1.15 early-season premium (everyone still has a full budget)" if early_season else "")
           + (f", capped at {int(cap)} of your ${budget_left} remaining" if raw > cap else ""))
    return bid, why


def waiver_recommendation(ctx, lineup_rec):
    week = ctx.upcoming_week
    up = ctx.latest.get("upcoming_week") or {}
    budget_total = up.get("waiver_budget_total") or config.FAAB_BUDGET_DEFAULT
    budget_left = budget_total - (up.get("waiver_budget_used") or 0)
    last_week = int(ctx.settings.get("playoff_week_start") or 15) + 2
    weeks_left = max(1, last_week - week + 1)
    early = week <= 4
    tkey = f"trending_adds_{config.TRENDING_LOOKBACK_H}h"
    my_vals = {v["player_id"]: v for v in lineup_rec["lineup"] + lineup_rec["bench"] if v.get("player_id")}
    my_qb1_bye = None
    qbs = sorted([v for v in my_vals.values() if v["pos"] == "QB"], key=lambda v: -(v.get("baseline") or 0))
    if qbs:
        my_qb1_bye = ctx.bye_week(qbs[0]["team"])
    # value my roster for the rest of the season
    mine = []
    for pid, v in my_vals.items():
        ros, how = ros_value(ctx, pid, week, v.get("sleeper"))
        protected = None
        if v["pos"] == "QB" and qbs and pid == qbs[0]["player_id"]:
            protected = "QB1"
        elif v["pos"] == "QB" and my_qb1_bye and week <= my_qb1_bye:
            protected = f"QB2 covers {qbs[0]['name']}'s week {my_qb1_bye} bye"
        elif v["pos"] == "DEF" and sum(1 for x in my_vals.values() if x["pos"] == "DEF") == 1:
            protected = "only DEF"
        mine.append(dict(v, ros=round(ros, 2), ros_how=how, protected=protected))
    droppable = sorted([m for m in mine if not m["protected"]], key=lambda m: m["ros"])
    starters_by_pos = {}
    for r in lineup_rec["lineup"]:
        if r.get("player_id"):
            starters_by_pos.setdefault(r["pos"], []).append(r)
    claims, seen = [], set()
    pool = []
    for pos, rows in (ctx.latest.get("waivers_by_position") or {}).items():
        for row in rows:
            pool.append(row)
    for row in ctx.latest.get("waivers_trending") or []:
        if row["player_id"] not in {p["player_id"] for p in pool}:
            pool.append(row)
    max_adds = max([row.get(tkey) or 0 for row in pool] + [1])

    def lineup_total(vals):
        lu, _ = build_lineup(vals, ctx.slots)
        return sum(r.get("expected") or 0 for r in lu)

    # weekly value used for roster math = rest-of-season value (not one week's matchup)
    base_vals = [dict(m, expected=m["ros"]) for m in mine]
    base_total = lineup_total(base_vals)
    for row in pool:
        pid = row["player_id"]
        if pid in seen or pid in my_vals:
            continue
        seen.add(pid)
        info = ctx.info(pid)
        pos = info["pos"] or row.get("pos")
        if pos not in config.FANTASY_POS:
            continue
        nxt = row.get("proj_next_week")
        ros, how = ros_value(ctx, pid, week, nxt)
        inj = ctx.injury(pid)
        status = inj.get("injury_status") if inj else row.get("injury_status")
        if status in ("Out", "IR", "PUP", "Sus"):
            continue
        value = 0.5 * (nxt or 0) + 0.5 * ros
        cand = {"player_id": pid, "name": info["name"] or row.get("name"), "pos": pos, "expected": ros, "ros": ros}
        # who would he replace? try each droppable player, keep the drop that leaves the best lineup
        best = None
        for d in droppable + ([m for m in mine if m["pos"] == "DEF"] if pos == "DEF" else []):
            if (pos == "DEF") != (d["pos"] == "DEF"):
                continue
            vals = [v for v in base_vals if v["player_id"] != d["player_id"]] + [cand]
            starter_gain = lineup_total(vals) - base_total
            # depth value: a bench upgrade is worth a fraction (injury and bye insurance)
            if pos == "QB" and starter_gain <= 0:
                qb_ros = sorted([m["ros"] for m in mine if m["pos"] == "QB"])
                cur_qb2 = qb_ros[0] if len(qb_ros) > 1 else 0
                depth_gain = max(0.0, ros - cur_qb2) / max(weeks_left, 1)   # only the bye week uses a QB2
            else:
                depth_gain = 0.25 * max(0.0, ros - d["ros"]) if starter_gain <= 0 else 0.0
            gain = starter_gain + depth_gain
            if best is None or gain > best[0]:
                best = (gain, d, starter_gain, depth_gain)
        if best is None:
            continue
        gain, drop, starter_gain, depth_gain = best
        would_start = starter_gain > 0.05
        bid, bid_why = bid_size(gain, weeks_left, row.get(tkey), budget_left, early, max_adds)
        claims.append({"player_id": pid, "name": info["name"] or row.get("name"), "pos": pos, "team": info["team"] or row.get("team"),
                       "opp_next": row.get("opponent_next_week"), "next_proj": nxt,
                       "last_actual": row.get(f"actual_week_{ctx.completed_week}"),
                       "ros": round(ros, 2), "ros_how": how, "value": round(value, 2), "gain": round(gain, 2),
                       "starter_gain": round(starter_gain, 2), "depth_gain": round(depth_gain, 2),
                       "trending": row.get(tkey) or 0, "injury_status": status, "would_start": would_start,
                       "drop": {"player_id": drop["player_id"], "name": drop["name"], "pos": drop["pos"], "ros": drop["ros"]},
                       "bid": bid, "bid_why": bid_why,
                       "why": (f"Rest-of-season value about {ros:.1f} a week ({how}; next week {nxt if nxt is not None else 'n/a'}). "
                               + (f"Adding him and dropping {drop['name']} lifts your weekly starting lineup by {starter_gain:+.1f}."
                                  if would_start else
                                  f"He would not start over anyone you have, so the gain is depth only: {depth_gain:+.1f} a week "
                                  f"(a quarter of his edge over {drop['name']}" + (", or just the bye week for a second QB" if pos == "QB" else "") + ")."))})
    claims.sort(key=lambda c: (-c["bid"], -c["gain"]))
    top = [c for c in claims if c["bid"] > 0][:8]
    flyers = [c for c in claims if c["bid"] == 0 and c["trending"] > 5000][:5]
    timing = ("Waivers clear Thursday 2:00 AM Central. This digest runs Wednesday 10:00 AM Central, so enter claims "
              "Wednesday. Dropped players sit on waivers for 2 days before becoming free agents.")
    assumptions = [
        "All 12 teams still hold their full $200 (0 used), so competition is at its maximum and bids run high.",
        "Gain = how much your weekly starting lineup improves (rest-of-season values) after the add and the drop. A player who "
        "would only sit on your bench counts a quarter of his edge over the player dropped; a second QB counts only his bye-week value.",
        "Bid formula: weekly gain x weeks left x $0.60, times a demand premium of up to 1.5x scaled to the hottest add on the wire, "
        "plus 15% in weeks 1-4. Capped at 45% of remaining budget (60% for a 5+ point gain). This is a judgment rule, "
        "not a calibrated model; the accuracy tracker will tell us over time whether the gains were real.",
        "Sleeper places every player who played last week on waivers until the Thursday run, so all listed players need a bid.",
    ]
    return {"week": week, "budget_left": budget_left, "budget_total": budget_total, "weeks_left": weeks_left,
            "claims": top, "flyers": flyers, "all_evaluated": len(claims), "drop_candidates": droppable[:5],
            "my_roster_values": sorted(mine, key=lambda m: -m["ros"]), "timing": timing, "assumptions": assumptions}
