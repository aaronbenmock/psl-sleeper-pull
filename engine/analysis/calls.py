"""Calls scorecard: grade last week's recommendations against what actually happened and what Aaron
actually did. Kept separate from projection accuracy (accuracy.py): this grades decisions, not numbers.

Freeze. Every build writes data/derived/calls/<season>/weekNN.json for the upcoming week:
  start/sit  the recommended lineup and every change / close call; a row freezes once either player's
             game has kicked off (the snapshot's `started` flag), so a call is never rewritten after
             the fact
  claims     the claims, the DEF streams and the speculative claims; frozen at the first waiver run
             after they were first recorded (Thursday 2:00 AM Central)
  synthesis  the structured calls the weekly news synthesis wrote into data/synthesis/latest.json
Weeks 2 to 4 were backfilled from git history by tools/backfill_calls.py (the source is recorded).

Grade, once data/weeks/<season>/weekNN_scored.json exists:
  start / sit   hit when the player recommended to start scored at least as much as the alternative.
                `followed` = Aaron started the recommended player and benched the other (matchups file).
  lineup        the recommended lineup in real points vs Aaron's actual lineup vs the optimal lineup
  def_stream    hit when the claimed DEF outscored the DEF it would have replaced that week
  claim         hit when the added player outscored the player he would have replaced, summed over every
                completed week from NN on (n weeks shown). `bid` / `won` from the transaction log.
  skip          (synthesis) hit when the alternative it preferred scored at least as much
A call whose player kicked off before the call was made is not graded.
"""
import datetime as dt
import os

from .. import store
from ..timeutil import parse_iso, iso, to_central
from .league_view import optimal_points

TYPES = ("start_sit", "def_stream", "claim", "speculative", "skip")


def calls_dir(data_dir, season):
    return os.path.join(data_dir, "derived", "calls", str(season))


def calls_path(data_dir, season, week):
    return os.path.join(calls_dir(data_dir, season), f"week{int(week):02d}.json")


def next_waiver_run(t_utc):
    """The first Thursday 2:00 AM Central at or after t (Sleeper's weekly waiver run in this league)."""
    c = to_central(t_utc)
    day = c.date()
    for i in range(8):
        d = day + dt.timedelta(days=i)
        if d.weekday() == 3:
            run_local = dt.datetime(d.year, d.month, d.day, 2, 0)
            off = c.utcoffset()
            run_utc = (run_local - off).replace(tzinfo=dt.timezone.utc)
            if run_utc >= t_utc:
                return run_utc
    return t_utc + dt.timedelta(days=7)


# ---------------------------------------------------------------- recording
def _ss_key(c):
    return f"{c['player_id']}>{c.get('alt_id')}"


def snapshot_calls(lineup, waivers, synth_meta, week):
    """Plain call lists from the current recommendation."""
    by_name = {r.get("name"): r for r in (lineup.get("lineup") or []) + (lineup.get("bench") or []) if r.get("player_id")}
    ss = []
    for c in lineup.get("changes") or []:
        a, b = by_name.get(c["in"]), by_name.get(c["out"])
        if a:
            ss.append({"type": "start_sit", "kind": "change", "player_id": a["player_id"], "name": a["name"],
                       "alt_id": (b or {}).get("player_id"), "alt_name": c["out"], "expected": c.get("in_expected"),
                       "alt_expected": c.get("out_expected"), "started": bool(a.get("started") or (b or {}).get("started"))})
    for c in lineup.get("close_calls") or []:
        a, b = by_name.get(c["starter"]), by_name.get(c["bench"])
        if a and b:
            ss.append({"type": "start_sit", "kind": "close_call", "player_id": a["player_id"], "name": a["name"],
                       "alt_id": b["player_id"], "alt_name": b["name"], "expected": a.get("expected"),
                       "alt_expected": b.get("expected"), "started": bool(a.get("started") or b.get("started"))})
    lu = [{"slot": r["slot"], "player_id": r.get("player_id"), "name": r.get("name"), "expected": r.get("expected"),
           "started": bool(r.get("started"))} for r in lineup.get("lineup") or []]
    cl = []
    for c in waivers.get("claims") or []:
        cl.append({"type": "def_stream" if c["pos"] == "DEF" else "claim", "player_id": c["player_id"], "name": c["name"],
                   "pos": c["pos"], "bid": c.get("bid"), "league_bid": c.get("league_bid"),
                   "alt_id": (c.get("drop") or {}).get("player_id"), "alt_name": (c.get("drop") or {}).get("name")})
    for c in waivers.get("speculative") or []:
        cl.append({"type": "speculative", "player_id": c["player_id"], "name": c["name"], "pos": c["pos"],
                   "bid": c.get("spec_bid"), "alt_id": (c.get("drop") or {}).get("player_id"),
                   "alt_name": (c.get("drop") or {}).get("name")})
    syn = []
    if synth_meta and int(synth_meta.get("week") or 0) == int(week):
        for c in synth_meta.get("calls") or []:
            if isinstance(c, dict) and c.get("type"):
                syn.append(dict(c, source="synthesis"))
    return ss, lu, cl, syn


def merge(existing, week, now, lineup, waivers, synth_meta, rec_source="live build"):
    """Merge the current recommendation into the stored calls file without rewriting anything frozen."""
    ss, lu, cl, syn = snapshot_calls(lineup, waivers, synth_meta, week)
    out = dict(existing or {})
    out.setdefault("week", int(week))
    out.setdefault("first_recorded_utc", iso(now))
    out.setdefault("source", rec_source)
    out["updated_utc"] = iso(now)
    # start/sit: frozen rows stay, live rows are replaced
    old_ss = [c for c in out.get("start_sit") or [] if c.get("frozen")]
    keys = {_ss_key(c) for c in old_ss}
    new_ss = []
    for c in ss:
        if _ss_key(c) in keys:
            continue
        if c["started"]:
            c = dict(c, frozen=True, frozen_at_utc=iso(now))
        new_ss.append(c)
    out["start_sit"] = old_ss + new_ss
    old_lu = {r["slot"] + str(i): r for i, r in enumerate(out.get("lineup") or [])}
    merged_lu = []
    for i, r in enumerate(lu):
        prev = old_lu.get(r["slot"] + str(i))
        if prev and prev.get("frozen"):
            merged_lu.append(prev)
        else:
            merged_lu.append(dict(r, frozen=r["started"]))
    out["lineup"] = merged_lu
    # claims freeze at the first waiver run after they were first recorded
    freeze_at = next_waiver_run(parse_iso(out["first_recorded_utc"]))
    out["claims_freeze_utc"] = iso(freeze_at)
    if not out.get("claims_frozen"):
        if now < freeze_at or "claims" not in out:
            # before the run the latest recommendation is the call; after it, keep what was recorded
            # before the run (only a file first written after the run takes the current list)
            out["claims"] = cl
            out["claims_rec_utc"] = iso(now)
        if now >= freeze_at:
            out["claims_frozen"] = True
    if syn:
        out["synthesis"] = syn
    return out


def record(ctx, lineup, waivers):
    path = calls_path(ctx.data_dir, ctx.season, ctx.upcoming_week)
    cur = store.read_json(path, {}) or {}
    new = merge(cur, ctx.upcoming_week, ctx.now, lineup, waivers, ctx.synthesis_meta)
    store.write_json(path, new)
    return new


# ---------------------------------------------------------------- grading
def _actual(scored, pid):
    row = (scored.get("players") or {}).get(pid) if pid else None
    if not row:
        return None
    return row.get("actual") if row.get("actual") is not None else 0.0


def _game_date(scored, pid):
    row = (scored.get("players") or {}).get(pid) if pid else None
    return (row or {}).get("date")


def _valid(scored, rec_utc, *pids):
    """False when one of the players' games was played before the call was made."""
    t = parse_iso(rec_utc)
    if not t:
        return True
    rec_day = to_central(t).strftime("%Y-%m-%d")
    for p in pids:
        d = _game_date(scored, p)
        if d and d < rec_day:
            return False
    return True


def grade_start_sit(c, scored, my_starters, rec_utc):
    a, b = _actual(scored, c["player_id"]), _actual(scored, c.get("alt_id"))
    g = dict(c)
    if a is None or b is None or not _valid(scored, rec_utc, c["player_id"], c.get("alt_id")):
        g["graded"] = False
        return g
    g.update(graded=True, actual=a, alt_actual=b, hit=a >= b,
             followed=(c["player_id"] in my_starters and c.get("alt_id") not in my_starters) if my_starters else None)
    return g


def grade_claim(c, scored_by_week, from_week, to_week, my_bids, rec_utc):
    g = dict(c)
    weeks = [w for w in range(from_week, to_week + 1) if w in scored_by_week]
    if not weeks or not c.get("alt_id"):
        g["graded"] = False
        return g
    if c["type"] == "def_stream" or c.get("one_week"):
        weeks = weeks[:1]
    a = sum((_actual(scored_by_week[w], c["player_id"]) or 0) for w in weeks)
    b = sum((_actual(scored_by_week[w], c["alt_id"]) or 0) for w in weeks)
    g.update(graded=True, actual=round(a, 2), alt_actual=round(b, 2), n_weeks=len(weeks), hit=a > b)
    bid = my_bids.get(c["player_id"])
    g["aaron_bid"] = bid["my_bid"] if bid else None
    g["aaron_won"] = (bid["result"] == "won") if bid else None
    g["winning_bid"] = bid["winning_bid"] if bid else None
    g["winner"] = bid["winner"] if bid else None
    return g


def grade_week(ctx, calls, market_rows):
    from . import market as mk
    w = int(calls["week"])
    scored = ctx.scored.get(w)
    if not scored:
        return None
    m = next((x for x in ctx.matchups.get(w) or [] if x.get("roster_id") == ctx.my_rid), {}) or {}
    my_starters = {s for s in m.get("starters") or [] if s and s != "0"}
    rec_utc = calls.get("first_recorded_utc")
    out = {"week": w, "source": calls.get("source"), "rows": []}
    for c in calls.get("start_sit") or []:
        out["rows"].append(dict(grade_start_sit(c, scored, my_starters, c.get("frozen_at_utc") or rec_utc), source="engine"))
    # what Aaron bid in the first run after the claims were made (within 4 days)
    t = parse_iso(calls.get("claims_rec_utc") or rec_utc)
    my_bids = {}
    if t:
        runs = sorted({r["run"] for r in market_rows if t.timestamp() <= r["run"] * 60 <= t.timestamp() + 4 * 86400})
        if runs:
            for b in mk.my_history([r for r in market_rows if r["run"] == runs[0]], ctx.my_rid):
                pid = next((r["player_id"] for r in market_rows if r["run"] == runs[0] and r["name"] == b["name"]), None)
                my_bids[pid] = b
    for c in calls.get("claims") or []:
        out["rows"].append(dict(grade_claim(c, ctx.scored, w, ctx.completed_week, my_bids, rec_utc), source="engine"))
    eng_drop = {c["player_id"]: (c.get("alt_id"), c.get("alt_name")) for c in calls.get("claims") or []}
    # a synthesis claim the engine did not list is measured against the engine's usual drop that week
    alts = [(c.get("alt_id"), c.get("alt_name")) for c in calls.get("claims") or [] if c.get("type") == "claim" and c.get("alt_id")]
    usual_drop = max(set(alts), key=alts.count) if alts else (None, None)
    for c in calls.get("synthesis") or []:
        c = dict(c)
        typ = c.get("type")
        if typ in ("start", "sit", "start_sit"):
            if typ == "sit":
                c["player_id"], c["alt_id"] = c.get("alt_id"), c.get("player_id")
                c["name"], c["alt_name"] = c.get("alt_name"), c.get("name")
            c["type"] = "start_sit"
            g = grade_start_sit(c, scored, my_starters, c.get("made_at_utc") or rec_utc)
        elif typ in ("claim", "def_stream"):
            if not c.get("alt_id"):
                c["alt_id"], c["alt_name"] = eng_drop.get(c.get("player_id")) or usual_drop
            g = grade_claim(c, ctx.scored, w, ctx.completed_week, my_bids, rec_utc)
        elif typ == "skip":
            a, b = _actual(scored, c.get("player_id")), _actual(scored, c.get("alt_id"))
            g = dict(c, graded=a is not None and b is not None)
            if g["graded"]:
                g.update(actual=a, alt_actual=b, hit=b >= a)
        else:
            g = dict(c, graded=False)
        out["rows"].append(dict(g, source="synthesis"))
    # lineup level
    lu_ids = [r["player_id"] for r in calls.get("lineup") or [] if r.get("player_id")]
    if lu_ids:
        rec_pts = round(sum((_actual(scored, p) or 0) for p in lu_ids), 2)
        pos_of = lambda p: ctx.info(p)["pos"]  # noqa: E731
        opt = optimal_points(m.get("players_points") or {}, m.get("players") or [], ctx.slots, pos_of) if m.get("players") else None
        out["lineup"] = {"recommended": rec_pts, "actual": m.get("points"), "optimal": opt,
                         "followed": sorted(set(lu_ids)) == sorted(my_starters) if my_starters else None,
                         "n_different": len(set(lu_ids) - my_starters) if my_starters else None}
    return out


def hit_rates(graded_weeks):
    table = {}
    for gw in graded_weeks:
        for r in gw["rows"]:
            if not r.get("graded"):
                continue
            key = (r["type"], r["source"])
            t = table.setdefault(key, {"type": r["type"], "source": r["source"], "n": 0, "hits": 0, "followed_n": 0, "followed": 0})
            t["n"] += 1
            t["hits"] += 1 if r.get("hit") else 0
            acted = r.get("followed")
            if r["type"] in ("claim", "def_stream", "speculative"):
                acted = r.get("aaron_bid") is not None      # for a claim, "followed" = he put in a bid
            if acted is not None:
                t["followed_n"] += 1
                t["followed"] += 1 if acted else 0
    rows = []
    for t in table.values():
        t["hit_rate"] = round(t["hits"] / t["n"], 3) if t["n"] else None
        rows.append(t)
    order = {k: i for i, k in enumerate(TYPES)}
    rows.sort(key=lambda t: (order.get(t["type"], 9), t["source"]))
    return rows


def build(ctx, market_rows):
    weeks = []
    for f in store.list_files(os.path.join(calls_dir(ctx.data_dir, ctx.season), "week*.json")):
        calls = store.read_json(f, {}) or {}
        if not calls.get("week") or int(calls["week"]) > ctx.completed_week:
            continue
        g = grade_week(ctx, calls, market_rows)
        if g:
            weeks.append(g)
    weeks.sort(key=lambda g: g["week"])
    lu = [g["lineup"] for g in weeks if g.get("lineup")]
    return {"weeks": weeks, "hit_rates": hit_rates(weeks), "latest": weeks[-1] if weeks else None,
            "lineup_totals": {"recommended": round(sum(x["recommended"] for x in lu), 1),
                              "actual": round(sum(x["actual"] or 0 for x in lu), 1),
                              "optimal": round(sum(x["optimal"] or 0 for x in lu), 1), "n_weeks": len(lu)} if lu else None,
            "note": ("Grades decisions, not projections. A start/sit call is a hit when the player recommended to start scored "
                     "at least as much as the alternative; a claim is a hit when the added player outscored the player he would "
                     "have replaced over the weeks since. Followed = what you actually did, from the Sleeper matchup and "
                     "transaction logs. Weeks 2 to 4 were reconstructed from git history; week 2's calls were made after its "
                     "Thursday game, so Thursday players are not graded.")}
