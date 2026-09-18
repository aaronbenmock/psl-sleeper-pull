"""League-wide view: how every team is performing and trending, with context-aware signals
(injured starters on a top scorer, luck, lineup efficiency, bye crunches, trade fits) instead
of a raw points table."""
import statistics

from .. import config
from .recommend import freshest_projections, FLEX_ELIGIBLE

INJ_TAGS = {"Questionable", "Doubtful", "Out", "IR", "PUP", "Sus"}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 2) if xs else None


def optimal_points(players_points, players, slots, pos_of):
    """Hindsight-best lineup from a roster's scored players."""
    pool = sorted(((players_points.get(p) or 0, p) for p in players), reverse=True)
    used, total = set(), 0.0
    for slot in slots:
        elig = FLEX_ELIGIBLE if slot == "FLEX" else {slot}
        for pts, p in pool:
            if p not in used and pos_of(p) in elig:
                used.add(p)
                total += pts
                break
    return round(total, 2)


def build(ctx, lineup_rec=None):
    week_next = ctx.upcoming_week
    completed = sorted(w for w in ctx.matchups if w <= ctx.completed_week and any((m.get("points") or 0) for m in ctx.matchups[w]))
    if not completed and ctx.completed_week and (ctx.latest.get("completed_week") or {}).get("league_scoreboard"):
        completed = [ctx.completed_week]
    rids = sorted({m["roster_id"] for w in ctx.matchups for m in ctx.matchups[w]} |
                  {r["roster_id"] for r in ctx.rosters} |
                  {row["roster_id"] for row in (ctx.latest.get("completed_week") or {}).get("league_scoreboard") or []})
    median_on = ctx.settings.get("league_average_match") == 1 or (ctx.meta.get("record_check") or {}).get("verdict", "").startswith("median")
    proj_next, src = freshest_projections(ctx, week_next, prefer_snapshot=True)
    pos_of = lambda p: ctx.info(p)["pos"]  # noqa: E731
    inj_table = (ctx.injuries or {}).get("players") or {}

    teams = {}
    weekly_scores = {}  # week -> {rid: points}
    for w in completed:
        rows = ctx.matchups.get(w) or []
        if rows:
            weekly_scores[w] = {m["roster_id"]: m.get("points") or 0 for m in rows}
        else:
            weekly_scores[w] = {row["roster_id"]: row["actual"] or 0 for row in
                                (ctx.latest.get("completed_week") or {}).get("league_scoreboard") or []}
    for rid in rids:
        roster = next((r for r in ctx.rosters if r.get("roster_id") == rid), {})
        st = roster.get("settings") or {}
        scores = [weekly_scores[w].get(rid) for w in completed if weekly_scores[w].get(rid) is not None]
        # head-to-head and all-play from matchups
        h2h_w = h2h_l = med_w = med_l = allplay_w = allplay_l = 0
        proj_totals, bench_left, eff = [], [], []
        for w in completed:
            rows = ctx.matchups.get(w) or []
            me = next((m for m in rows if m["roster_id"] == rid), None)
            if not me:
                continue
            opp = next((m for m in rows if m.get("matchup_id") == me.get("matchup_id") and m["roster_id"] != rid), None)
            if opp:
                if (me.get("points") or 0) > (opp.get("points") or 0):
                    h2h_w += 1
                elif (me.get("points") or 0) < (opp.get("points") or 0):
                    h2h_l += 1
            pts_all = sorted(weekly_scores[w].values())
            if len(pts_all) >= 2:
                med = (pts_all[len(pts_all) // 2 - 1] + pts_all[len(pts_all) // 2]) / 2 if len(pts_all) % 2 == 0 else pts_all[len(pts_all) // 2]
                if (me.get("points") or 0) > med:
                    med_w += 1
                else:
                    med_l += 1
            others = [v for r2, v in weekly_scores[w].items() if r2 != rid]
            allplay_w += sum(1 for v in others if (me.get("points") or 0) > v)
            allplay_l += sum(1 for v in others if (me.get("points") or 0) < v)
            scored = (ctx.scored.get(w) or {}).get("players") or {}
            starters = [s for s in me.get("starters") or [] if s and s != "0"]
            if scored:
                proj_totals.append(round(sum((scored.get(s) or {}).get("proj") or 0 for s in starters), 2))
            pp = me.get("players_points") or {}
            if pp and me.get("players"):
                opt = optimal_points(pp, me["players"], ctx.slots, pos_of)
                bench_left.append(round(opt - (me.get("points") or 0), 2))
                eff.append(round((me.get("points") or 0) / opt, 3) if opt else None)
        # roster health now
        starters_now = [s for s in roster.get("starters") or [] if s and s != "0"]
        injured = []
        for s in starters_now:
            row = inj_table.get(s) or {}
            status = row.get("injury_status") or (ctx.players.get(s) or {}).get("injury_status")
            if status in INJ_TAGS:
                injured.append({"name": ctx.name(s), "pos": pos_of(s), "status": status,
                                "body": row.get("injury_body_part") or (ctx.players.get(s) or {}).get("injury_body_part")})
        byes_next = [ctx.name(s) for s in starters_now if ctx.info(s)["team"] and ctx.bye_week(ctx.info(s)["team"]) == week_next]
        covered = [s for s in starters_now if (proj_next.get(s) or {}).get("p") is not None or (ctx.info(s)["team"] and ctx.bye_week(ctx.info(s)["team"]) == week_next)]
        proj_next_total = (round(sum(((proj_next.get(s) or {}).get("p") or 0) for s in starters_now), 2)
                           if starters_now and proj_next and len(covered) >= 0.8 * len(starters_now) else None)
        # remaining schedule
        future_opps = []
        for w, rows in ctx.matchups.items():
            if w <= ctx.completed_week:
                continue
            me = next((m for m in rows if m["roster_id"] == rid), None)
            if me:
                opp = next((m for m in rows if m.get("matchup_id") == me.get("matchup_id") and m["roster_id"] != rid), None)
                if opp:
                    future_opps.append(opp["roster_id"])
        teams[rid] = {
            "roster_id": rid, "team": ctx.team_name(rid), "manager": ctx.manager_name(rid), "is_mine": rid == ctx.my_rid,
            "wins": st.get("wins"), "losses": st.get("losses"), "ties": st.get("ties"),
            "h2h": f"{h2h_w}-{h2h_l}", "median": f"{med_w}-{med_l}" if median_on else None,
            "allplay": f"{allplay_w}-{allplay_l}", "allplay_pct": round(allplay_w / (allplay_w + allplay_l), 3) if allplay_w + allplay_l else None,
            "scores": scores, "avg": _mean(scores), "last": scores[-1] if scores else None,
            "pf": round(sum(scores), 2), "proj_totals": proj_totals,
            "vs_proj": round(sum(scores[:len(proj_totals)]) - sum(proj_totals), 2) if proj_totals else None,
            "bench_left": bench_left, "efficiency": _mean(eff),
            "injured_starters": injured, "byes_next": byes_next, "proj_next": proj_next_total,
            "future_opps": future_opps, "faab_used": st.get("waiver_budget_used"),
            "starters_now": [{"name": ctx.name(s), "pos": pos_of(s)} for s in starters_now],
        }
    # trend, power, schedule strength (need the full table first)
    avgs = {rid: t["avg"] for rid, t in teams.items() if t["avg"] is not None}
    league_avg = _mean(list(avgs.values()))
    for rid, t in teams.items():
        sc = t["scores"]
        if len(sc) >= 3:
            n = len(sc)
            xm = (n - 1) / 2
            slope = sum((i - xm) * (s - t["avg"]) for i, s in enumerate(sc)) / sum((i - xm) ** 2 for i in range(n))
            t["trend"] = round(slope, 1)
            t["trend_label"] = "rising" if slope > 4 else "falling" if slope < -4 else "flat"
        elif len(sc) == 2:
            t["trend"] = round(sc[-1] - sc[0], 1)
            t["trend_label"] = "up" if t["trend"] > 8 else "down" if t["trend"] < -8 else "flat"
        else:
            t["trend"] = None
            t["trend_label"] = "n/a (1 week)"
        opp_avgs = [avgs.get(o) for o in t["future_opps"] if avgs.get(o) is not None]
        t["sos_remaining"] = _mean(opp_avgs)
        base = t["avg"] if t["avg"] is not None else (league_avg or 0)
        nxt = t["proj_next"] if t["proj_next"] is not None else base
        t["power"] = round(0.6 * base + 0.4 * nxt, 1)
    ranked = sorted(teams.values(), key=lambda t: -(t["power"] or 0))
    for i, t in enumerate(ranked, 1):
        t["power_rank"] = i
    by_avg = sorted(teams.values(), key=lambda t: -(t["avg"] or 0))
    for i, t in enumerate(by_avg, 1):
        t["pf_rank"] = i

    # ---- signals
    signals = []
    n_weeks = len(completed)
    my = teams.get(ctx.my_rid) or {}
    my_pos_counts = {}
    for r in (lineup_rec or {}).get("lineup", []) + (lineup_rec or {}).get("bench", []):
        if r.get("pos"):
            my_pos_counts[r["pos"]] = my_pos_counts.get(r["pos"], 0) + 1
    my_surplus = [p for p, c in my_pos_counts.items() if p in ("WR", "RB") and c >= 6]
    for t in teams.values():
        who = t["team"] + (" (you)" if t["is_mine"] else "")
        inj = t["injured_starters"]
        if len(inj) >= 2:
            names = ", ".join(f"{i['name']} {i['status']}" + (f" ({i['body']})" if i.get("body") else "") for i in inj)
            sev = "high" if t.get("pf_rank", 99) <= 4 else "medium"
            lead = (f"{who} is the #{t['pf_rank']} scorer at {t['avg']} a week but " if t.get("pf_rank", 99) <= 4 and t["avg"] else f"{who} ")
            signals.append({"team": t["team"], "kind": "injured_starters", "severity": sev,
                            "text": f"{lead}has {len(inj)} of {len(t['starters_now']) or 8} starters carrying injury tags: {names}."})
        elif len(inj) == 1 and t.get("pf_rank", 99) <= 3:
            i = inj[0]
            signals.append({"team": t["team"], "kind": "injured_starter", "severity": "low",
                            "text": f"{who} (#{t['pf_rank']} scorer) has {i['name']} listed {i['status']}."})
        if len(t["byes_next"]) >= 2:
            signals.append({"team": t["team"], "kind": "bye_crunch", "severity": "medium",
                            "text": f"{who} has {len(t['byes_next'])} current starters on bye in week {week_next}: {', '.join(t['byes_next'])}."})
        if n_weeks >= 2 and t["last"] is not None and t["avg"] is not None:
            sd = statistics.pstdev(t["scores"]) if len(t["scores"]) > 1 else 0
            if t["last"] - t["avg"] > max(15, sd):
                signals.append({"team": t["team"], "kind": "hot", "severity": "low",
                                "text": f"{who} scored {t['last']} last week, {t['last'] - t['avg']:.0f} above its average of {t['avg']}."})
            if t["avg"] - t["last"] > max(15, sd):
                signals.append({"team": t["team"], "kind": "cold", "severity": "low",
                                "text": f"{who} scored {t['last']} last week, {t['avg'] - t['last']:.0f} below its average of {t['avg']}."})
        if t["allplay_pct"] is not None and t["wins"] is not None and n_weeks >= 1:
            games = (t["wins"] or 0) + (t["losses"] or 0) + (t["ties"] or 0)
            if games:
                exp_w = t["allplay_pct"] * games
                if (t["wins"] or 0) - exp_w >= 1.0:
                    signals.append({"team": t["team"], "kind": "lucky", "severity": "low",
                                    "text": f"{who} is {t['wins']}-{t['losses']} but would be about {exp_w:.1f}-{games - exp_w:.1f} against the whole league each week (all-play {t['allplay']}). Record flatters the roster."})
                elif exp_w - (t["wins"] or 0) >= 1.0:
                    signals.append({"team": t["team"], "kind": "unlucky", "severity": "low",
                                    "text": f"{who} is {t['wins']}-{t['losses']} but would be about {exp_w:.1f}-{games - exp_w:.1f} against the whole league (all-play {t['allplay']}). Better than the record."})
        if t["vs_proj"] is not None and n_weeks >= 2 and abs(t["vs_proj"]) / n_weeks >= 15:
            d = t["vs_proj"] / n_weeks
            signals.append({"team": t["team"], "kind": "vs_projection", "severity": "low",
                            "text": f"{who} has {'beaten' if d > 0 else 'missed'} Sleeper's starter projections by {abs(d):.0f} points a week"
                                    + (" (n=1, expect regression)." if n_weeks == 1 else f" over {n_weeks} weeks.")})
        if t["bench_left"] and t["bench_left"][-1] >= 25 and (t["is_mine"] or t.get("pf_rank", 99) <= 6):
            w_idx = len(t["bench_left"]) - 1
            signals.append({"team": t["team"], "kind": "bench_points", "severity": "low",
                            "text": f"{who} left {max(t['bench_left']):.0f} points on the bench in week {completed[w_idx] if w_idx < len(completed) else '?'} (lineup efficiency {t['efficiency'] * 100:.0f}%)." if t["efficiency"] else
                                    f"{who} left {max(t['bench_left']):.0f} points on the bench."})
        # trade fit: their weakest starting slot vs my surplus
        if not t["is_mine"] and my_surplus and t["starters_now"] and proj_next:
            roster = next((r for r in ctx.rosters if r.get("roster_id") == t["roster_id"]), {})
            starters_now = [s for s in roster.get("starters") or [] if s and s != "0"]
            weak = sorted(((((proj_next.get(s) or {}).get("p") or 0), s) for s in starters_now if pos_of(s) in my_surplus))
            if weak and weak[0][0] < 7.5:
                pts, s = weak[0]
                signals.append({"team": t["team"], "kind": "trade_fit", "severity": "info",
                                "text": f"{who} starts {ctx.name(s)} ({pos_of(s)}) at a projected {pts:.1f}; you carry {my_pos_counts.get(pos_of(s))} {pos_of(s)}s. Possible trade partner (deadline week {ctx.settings.get('trade_deadline') or 12})."})
    sev_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    my_name = (teams.get(ctx.my_rid) or {}).get("team")
    signals.sort(key=lambda s: (sev_order.get(s["severity"], 9), s["team"] != my_name, s["team"]))
    fits = [s for s in signals if s["kind"] == "trade_fit"]
    signals = [s for s in signals if s["kind"] != "trade_fit"] + fits[:3]
    signals = signals[:16]
    notes = []
    if n_weeks < 3:
        notes.append(f"Trend lines need 3 completed weeks; {n_weeks} available. Hot/cold and luck signals are suppressed or marked n=1.")
    if median_on:
        notes.append("This league plays a second game against the league median every week, which is why records add up to two games per week (your 2-0 after week 1).")
    if not ctx.rosters:
        notes.append("Roster detail (injured starters, byes, projected next week) needs the v1.2 pull; only the scoreboard from the v1.1 pull is available.")
    return {"week_next": week_next, "weeks_completed": completed, "median_game": median_on, "league_avg": league_avg,
            "teams": ranked, "signals": signals, "notes": notes, "projection_source": src}
