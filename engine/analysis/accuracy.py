"""Accuracy tracking against three named baselines, per completed week and pooled.

Baselines (what each one predicts for a player's points in week W):
  A. sleeper   Sleeper's projection. Pre-kickoff snapshot value when one exists for that player
               (frozen before his team's game started); otherwise the value Sleeper stored by the
               Wednesday pull, labeled "post-hoc".
  B. preseason The v2.0 rankings' proj_ppg (VOR model) for skill players, wtd_def_ppg for a DEF.
               A constant per player all season.
  C. naive     Season-to-date average points before week W. Undefined in week 1.

Three player pools, so every projection the engine acts on is graded, not just the ones on a
roster:
  started    every player started by any of the 12 teams that week (n about 96)
  rostered   every player on any of the 12 rosters (n about 190)
  waiver     every player NOT on any roster whose Sleeper projection for that week was at least
             WAIVER_PROJ_MIN points (n about 100). These are the numbers the waiver engine reads
             when it prices a claim, so until this pool existed the FAAB bids rested on a
             projection whose error had never been measured. The cut keeps out the ~700 cached
             players Sleeper projects near zero, whose errors would flatter every baseline.

Two levels:
  player-level  MAE, bias (actual minus predicted), Spearman rank correlation, per pool.
  lineup-level  For each of the 12 rosters, the lineup each baseline would have started from that
                roster, scored with real points, compared with the hindsight-optimal lineup and
                with what the manager actually started. This is the decision that matters.

Also measured: DEF bias (actual minus projection, and the part explained by the two stat
categories Sleeper never projects), pre-kickoff snapshot coverage, and post-hoc drift
(Wednesday's stored projection vs the frozen snapshot; tells us whether week 1's post-hoc
numbers, taken before snapshots existed, can be trusted).
"""
import os
import statistics

from .. import store
from .recommend import FLEX_ELIGIBLE

BASELINES = ["sleeper", "preseason", "naive"]
POOLS = ["started", "rostered", "waiver"]
WAIVER_PROJ_MIN = 5.0      # a non-rostered player is graded only if Sleeper projected him this high


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 2) if xs else None


def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def spearman(pred, act):
    pairs = [(p, a) for p, a in zip(pred, act) if p is not None and a is not None]
    if len(pairs) < 3:
        return None
    rp = _rank([p for p, _ in pairs])
    ra = _rank([a for _, a in pairs])
    mp, ma = statistics.mean(rp), statistics.mean(ra)
    num = sum((x - mp) * (y - ma) for x, y in zip(rp, ra))
    den = (sum((x - mp) ** 2 for x in rp) * sum((y - ma) ** 2 for y in ra)) ** 0.5
    return round(num / den, 3) if den else None


def player_metrics(pred, act):
    pairs = [(p, a) for p, a in zip(pred, act) if p is not None and a is not None]
    if not pairs:
        return {"n": 0, "mae": None, "bias": None, "spearman": None}
    return {"n": len(pairs), "mae": round(statistics.mean(abs(a - p) for p, a in pairs), 2),
            "bias": round(statistics.mean(a - p for p, a in pairs), 2),
            "spearman": spearman([p for p, _ in pairs], [a for _, a in pairs])}


def greedy_lineup(players, score_of, slots, pos_of):
    pool = sorted(players, key=lambda p: -(score_of(p) or 0))
    used, chosen = set(), []
    for slot in slots:
        elig = FLEX_ELIGIBLE if slot == "FLEX" else {slot}
        for p in pool:
            if p not in used and pos_of(p) in elig and (score_of(p) is not None):
                used.add(p)
                chosen.append(p)
                break
    return chosen


def pre_kickoff_projection(ctx, week, snaps_cache):
    """dict pid -> (pts, snapshot label) using the latest snapshot taken before that player's team started."""
    if week in snaps_cache:
        return snaps_cache[week]
    out = {}
    for s in ctx.snap_index:
        if s.get("week") != week:
            continue
        rel = s["path"].replace("data/", "", 1).split("/")
        snap = store.read_json(os.path.join(ctx.data_dir, *rel), {})
        for pid, row in (snap.get("players") or {}).items():
            if not row.get("started") and row.get("p") is not None:
                out[pid] = (row["p"], s.get("label"), s.get("taken_at_utc"))
    snaps_cache[week] = out
    return out


def week_report(ctx, week, snaps_cache):
    scored = (ctx.scored.get(week) or {}).get("players") or {}
    rows = ctx.matchups.get(week) or []
    if not scored or not rows:
        return None
    pos_of = lambda p: (scored.get(p) or {}).get("pos") or ctx.info(p)["pos"]  # noqa: E731
    pre = pre_kickoff_projection(ctx, week, snaps_cache)

    def preds(pid):
        s = scored.get(pid) or {}
        if pid in pre:
            sl, src = pre[pid][0], "snapshot"
        else:
            sl, src = s.get("proj"), "post-hoc"
        pre_ppg = ctx.preseason_ppg(pid, pos_of(pid), s.get("team") or ctx.info(pid)["team"])
        avg, n = ctx.season_avg(pid, before_week=week)
        return {"sleeper": sl, "preseason": pre_ppg, "naive": avg if n else None, "src": src}

    def actual_of(pid, m=None):
        if m and (m.get("players_points") or {}).get(pid) is not None:
            return m["players_points"][pid]
        return (scored.get(pid) or {}).get("actual")

    started, rostered, waiver = [], [], []
    lineup_rows = []
    for m in rows:
        rid = m["roster_id"]
        starters = [s for s in m.get("starters") or [] if s and s != "0"]
        players = [p for p in m.get("players") or [] if p and p != "0"] or starters
        pp = {p: actual_of(p, m) for p in players}
        for p in starters:
            started.append((p, preds(p), pp.get(p)))
        for p in players:
            rostered.append((p, preds(p), pp.get(p)))
        pred_cache = {p: preds(p) for p in players}
        actual_pts = m.get("points") or round(sum(pp.get(p) or 0 for p in starters), 2)
        optimal = greedy_lineup(players, lambda p: pp.get(p), ctx.slots, pos_of)
        opt_pts = round(sum(pp.get(p) or 0 for p in optimal), 2)
        line = {"roster_id": rid, "team": ctx.team_name(rid), "is_mine": rid == ctx.my_rid,
                "actual": actual_pts, "optimal": opt_pts}
        for b in BASELINES:
            if b == "naive" and week == 1:
                line[b] = None
                continue
            chosen = greedy_lineup(players, lambda p, b=b: pred_cache[p][b], ctx.slots, pos_of)
            if len(chosen) < len(ctx.slots):
                # baseline could not fill the lineup (missing predictions): fill the rest by Sleeper
                rest = greedy_lineup([p for p in players if p not in chosen], lambda p: pred_cache[p]["sleeper"],
                                     [s for i, s in enumerate(ctx.slots) if i >= len(chosen)], pos_of)
                chosen = chosen + rest
            line[b] = round(sum(pp.get(p) or 0 for p in chosen), 2)
        lineup_rows.append(line)

    # third pool: the waiver engine's inputs. Every player Sleeper projected at WAIVER_PROJ_MIN or
    # more who was on nobody's roster that week. The snapshots already froze a projection for all
    # ~3,150 projected players, so no new collection was needed; only the scoring pool widened.
    on_a_roster = set()
    for m in rows:
        on_a_roster.update(p for p in (m.get("players") or []) if p and p != "0")
        on_a_roster.update(p for p in (m.get("starters") or []) if p and p != "0")
    for pid, srow in scored.items():
        if pid in on_a_roster or srow.get("actual") is None:
            continue
        pr = preds(pid)
        if pr["sleeper"] is None or pr["sleeper"] < WAIVER_PROJ_MIN:
            continue
        waiver.append((pid, pr, srow.get("actual")))

    def level(pairs):
        out = {}
        for b in BASELINES:
            out[b] = player_metrics([pr[b] for _, pr, _ in pairs], [a for _, _, a in pairs])
        out["n_players"] = len(pairs)
        out["sleeper_from_snapshot"] = sum(1 for _, pr, _ in pairs if pr["src"] == "snapshot")
        return out

    lineup_summary = {}
    for b in BASELINES:
        vals = [l[b] for l in lineup_rows if l.get(b) is not None]
        if not vals:
            lineup_summary[b] = None
            continue
        opt = [l["optimal"] for l in lineup_rows if l.get(b) is not None]
        act = [l["actual"] for l in lineup_rows if l.get(b) is not None]
        lineup_summary[b] = {"n_teams": len(vals), "avg_points": round(statistics.mean(vals), 2),
                             "pct_of_optimal": round(100 * sum(vals) / sum(opt), 1) if sum(opt) else None,
                             "vs_manager": round(statistics.mean(v - a for v, a in zip(vals, act)), 2),
                             "beat_manager": sum(1 for v, a in zip(vals, act) if v > a + 0.01)}
    lineup_summary["manager"] = {"avg_points": _mean([l["actual"] for l in lineup_rows]),
                                 "pct_of_optimal": round(100 * sum(l["actual"] for l in lineup_rows) / sum(l["optimal"] for l in lineup_rows), 1)}
    mine = next((l for l in lineup_rows if l["is_mine"]), None)

    # DEF bias
    defs = [(pid, s) for pid, s in scored.items() if s.get("pos") == "DEF" and s.get("actual") is not None and s.get("proj") is not None]
    def_bias = {"n": len(defs), "bias": _mean([s["actual"] - s["proj"] for _, s in defs]),
                "mae": _mean([abs(s["actual"] - s["proj"]) for _, s in defs]),
                "unprojected_pts": _mean([s.get("unprojected_pts") for _, s in defs]),
                "note": "unprojected_pts = points from 3-and-outs and 4th-down stops, which Sleeper scores but never projects"}
    started_defs = [(p, pr, a) for p, pr, a in started if pos_of(p) == "DEF"]
    def_bias["started_n"] = len(started_defs)
    def_bias["started_bias"] = _mean([a - pr["sleeper"] for _, pr, a in started_defs if pr["sleeper"] is not None and a is not None])
    # post-hoc drift: Wednesday stored projection vs the pre-kickoff snapshot
    drift = [abs((scored.get(p) or {}).get("proj") - pre[p][0]) for p in pre if (scored.get(p) or {}).get("proj") is not None]
    coverage = {"starters_with_snapshot": sum(1 for p, pr, _ in started if pr["src"] == "snapshot"), "starters": len(started),
                "posthoc_drift_mae": _mean(drift), "posthoc_drift_n": len(drift)}
    return {"week": week, "started": level(started), "rostered": level(rostered), "waiver": level(waiver),
            "waiver_cut": WAIVER_PROJ_MIN, "lineups": lineup_summary,
            "lineup_rows": lineup_rows, "mine": mine, "def_bias": def_bias, "coverage": coverage}


def build(ctx):
    snaps_cache = {}
    weeks = []
    for w in sorted(ctx.scored):
        if w > ctx.completed_week:
            continue
        rep = week_report(ctx, w, snaps_cache)
        if rep:
            weeks.append(rep)
    # fallback for day one: only the v1.1 latest.json exists (no scored file, no matchups)
    fallback = None
    if not weeks and ctx.latest.get("completed_week"):
        c = ctx.latest["completed_week"]
        rows = [r for r in (c.get("starters") or []) + (c.get("bench") or []) if r.get("projected") is not None and r.get("actual") is not None]
        pre = [(r, ctx.preseason_ppg(r["player_id"], r["pos"], r["team"])) for r in rows]
        fallback = {"week": c["week"], "n": len(rows), "scope": "your roster only (v1.1 pull)",
                    "sleeper": player_metrics([r["projected"] for r in rows], [r["actual"] for r in rows]),
                    "preseason": player_metrics([p for _, p in pre], [r["actual"] for r, _ in pre]),
                    "naive": {"n": 0, "mae": None, "bias": None, "spearman": None}}
    pooled = {}
    for lvl in POOLS:
        pooled[lvl] = {}
        for b in BASELINES:
            maes = [(w[lvl][b]["mae"], w[lvl][b]["n"]) for w in weeks if w[lvl][b]["n"]]
            biases = [(w[lvl][b]["bias"], w[lvl][b]["n"]) for w in weeks if w[lvl][b]["n"]]
            n = sum(k for _, k in maes)
            pooled[lvl][b] = {"n": n, "mae": round(sum(m * k for m, k in maes) / n, 2) if n else None,
                              "bias": round(sum(m * k for m, k in biases) / n, 2) if n else None,
                              "weeks": len(maes)}
    pooled["lineups"] = {}
    for b in BASELINES + ["manager"]:
        vals = [w["lineups"][b] for w in weeks if w["lineups"].get(b)]
        if vals:
            pooled["lineups"][b] = {"weeks": len(vals), "avg_points": _mean([v["avg_points"] for v in vals]),
                                    "pct_of_optimal": _mean([v["pct_of_optimal"] for v in vals]),
                                    "vs_manager": _mean([v.get("vs_manager") for v in vals]) if b != "manager" else None}
    n_weeks = len(weeks)
    honesty = []
    if n_weeks <= 1:
        honesty.append(f"n = {n_weeks} completed week{'s' if n_weeks != 1 else ''}. Nothing here is a finding yet. "
                       "The job of this page is to accumulate; treat differences between baselines as noise until 6+ weeks.")
    elif n_weeks < 6:
        honesty.append(f"n = {n_weeks} weeks. Early. Differences under about 1 point of MAE are within week-to-week noise.")
    if weeks and weeks[0]["coverage"]["starters_with_snapshot"] == 0:
        honesty.append("Week 1 has no pre-kickoff snapshot (the snapshot job did not exist yet), so its Sleeper baseline is the "
                       "post-hoc value stored by the Wednesday pull. From week 2 the post-hoc drift metric tells us how much that matters.")
    honesty.append("The naive baseline (start the highest season-average scorer) is undefined in week 1 and thin until week 4.")
    wv = (pooled.get("waiver") or {}).get("sleeper") or {}
    if wv.get("n"):
        honesty.append(f"The waiver pool grades the projections the FAAB bids are built on: {wv['n']} player-weeks of "
                       f"non-rostered players Sleeper projected at {WAIVER_PROJ_MIN}+ points. A free agent is a different "
                       "population from a starter (more part-time roles, more zeroes), so compare it with the other pools "
                       "carefully rather than reading one MAE against the other.")
    history = {"generated_at_utc": ctx.now.isoformat().replace("+00:00", "Z"), "weeks": weeks, "pooled": pooled,
               "fallback": fallback, "honesty": honesty, "pools": POOLS, "waiver_cut": WAIVER_PROJ_MIN, "baselines": {
                   "sleeper": "Sleeper's projection, frozen pre-kickoff when a snapshot exists (else post-hoc)",
                   "preseason": "v2.0 preseason model proj_ppg (VOR ranking), constant all season",
                   "naive": "start the highest season-to-date average scorer (undefined week 1)"}}
    store.write_json(os.path.join(ctx.data_dir, "derived", "accuracy_history.json"), history)
    return history
