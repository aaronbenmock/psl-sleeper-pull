"""Backtesting scaffold for the forecasting proposal (stretch item 2).

Replays every completed week with the frozen data and scores candidate models the same way
the accuracy page scores the baselines: player MAE over league starters, and lineup points
captured over all 12 rosters. Candidates today:

  blend(w, k)     expected = w x Sleeper + (1 - w) x (n x avg + k x preseason) / (n + k)
                  w in {0.5, 0.65, 0.8, 1.0}, k in {2, 4, 8}
  def_fix(on)     add each defense's 2025 three-and-out points (0.5 x rate) to Sleeper's DEF number

It refuses to draw conclusions before 4 completed weeks and says so. Output:
data/derived/backtest.json and data/derived/backtest.md. Run: python engine.py backtest
"""
import itertools
import os
import statistics

from .. import store
from .accuracy import pre_kickoff_projection, greedy_lineup, player_metrics, BASELINES  # noqa: F401

MIN_WEEKS = 4
W_GRID = [0.5, 0.65, 0.8, 1.0]
K_GRID = [2, 4, 8]


def _pred(ctx, scored, pre, pid, week, w, k, def_fix):
    s = scored.get(pid) or {}
    sl = pre[pid][0] if pid in pre else s.get("proj")
    if sl is None:
        return None
    pos = s.get("pos") or ctx.info(pid)["pos"]
    team = s.get("team") or ctx.info(pid)["team"]
    if def_fix and pos == "DEF":
        d = ctx.def_rankings.get(team) or {}
        sl = sl + 0.5 * (d.get("three_and_out_pg_2025") or 0)
    pre_ppg = ctx.preseason_ppg(pid, pos, team)
    avg, n = ctx.season_avg(pid, before_week=week)
    if pre_ppg is None and avg is None:
        base = None
    elif pre_ppg is None:
        base = avg
    elif avg is None:
        base = pre_ppg
    else:
        base = (n * avg + k * pre_ppg) / (n + k)
    if base is None or w >= 1.0:
        return sl
    return w * sl + (1 - w) * base


def build(ctx):
    weeks = sorted(w for w in ctx.scored if w <= ctx.completed_week and ctx.matchups.get(w))
    snaps_cache = {}
    candidates = [{"name": f"blend w={w} k={k}{' +deffix' if d else ''}", "w": w, "k": k, "def_fix": d}
                  for w, k, d in itertools.product(W_GRID, K_GRID, [False, True])
                  if not (w >= 1.0 and k != K_GRID[0])]
    results = {c["name"]: {"mae": [], "lineup": [], "n": 0} for c in candidates}
    for week in weeks:
        scored = (ctx.scored[week].get("players") or {})
        pre = pre_kickoff_projection(ctx, week, snaps_cache)
        rows = ctx.matchups[week]
        pos_of = lambda p: (scored.get(p) or {}).get("pos") or ctx.info(p)["pos"]  # noqa: E731
        for c in candidates:
            preds, acts, lineup_pts = [], [], []
            for m in rows:
                players = [p for p in m.get("players") or [] if p and p != "0"]
                starters = [s for s in m.get("starters") or [] if s and s != "0"]
                pp = m.get("players_points") or {}
                cache = {p: _pred(ctx, scored, pre, p, week, c["w"], c["k"], c["def_fix"]) for p in players}
                for s in starters:
                    a = pp.get(s) if pp.get(s) is not None else (scored.get(s) or {}).get("actual")
                    if cache.get(s) is not None and a is not None:
                        preds.append(cache[s])
                        acts.append(a)
                chosen = greedy_lineup(players, lambda p: cache.get(p), ctx.slots, pos_of)
                lineup_pts.append(sum((pp.get(p) if pp.get(p) is not None else (scored.get(p) or {}).get("actual") or 0) for p in chosen))
            pm = player_metrics(preds, acts)
            results[c["name"]]["mae"].append(pm["mae"])
            results[c["name"]]["lineup"].append(round(statistics.mean(lineup_pts), 2) if lineup_pts else None)
            results[c["name"]]["n"] += pm["n"]
    table = []
    for c in candidates:
        r = results[c["name"]]
        maes = [x for x in r["mae"] if x is not None]
        lus = [x for x in r["lineup"] if x is not None]
        table.append({"model": c["name"], "weeks": len(maes), "n": r["n"],
                      "mae": round(statistics.mean(maes), 2) if maes else None,
                      "lineup_avg": round(statistics.mean(lus), 2) if lus else None,
                      "by_week_mae": r["mae"], "by_week_lineup": r["lineup"]})
    table.sort(key=lambda t: -(t["lineup_avg"] or 0))
    verdict = (f"Insufficient data: {len(weeks)} completed week(s), need {MIN_WEEKS}. Table is scaffolding only."
               if len(weeks) < MIN_WEEKS else
               f"{len(weeks)} weeks. Best lineup capture: {table[0]['model']} ({table[0]['lineup_avg']}); "
               f"Sleeper alone: {next((t['lineup_avg'] for t in table if t['model'].startswith('blend w=1.0 k=2') and 'deffix' not in t['model']), None)}. "
               "Treat gaps under 1 point as noise until 8+ weeks.")
    out = {"generated_at_utc": ctx.now.isoformat().replace("+00:00", "Z"), "weeks": weeks, "min_weeks": MIN_WEEKS,
           "verdict": verdict, "table": table}
    store.write_json(os.path.join(ctx.data_dir, "derived", "backtest.json"), out)
    md = [f"# Backtest ({len(weeks)} completed weeks)", "", verdict, "",
          "| Model | Weeks | n | Player MAE | Lineup points captured (avg per team) |", "|---|---|---|---|---|"]
    for t in table:
        md.append(f"| {t['model']} | {t['weeks']} | {t['n']} | {t['mae']} | {t['lineup_avg']} |")
    store.write_text(os.path.join(ctx.data_dir, "derived", "backtest.md"), "\n".join(md) + "\n")
    return out
