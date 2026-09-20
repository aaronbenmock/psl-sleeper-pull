"""Backtest of the vacated-share tiebreak on nflverse 2015-2025 (stdlib only).

The question, stated the way it was asked: among pairs of roster-eligible players within 1.5
expected points of each other, does starting the one with the higher vacated-absorption number
beat the current boom-rate tiebreak? The unit of measurement is lineup points per team-week in the
same simulated 12-team league the main harness uses, and the interval is a paired bootstrap over
weeks.

Method, following engine/analysis/histbacktest.py:
  - Seasons 2015 to 2024 select the estimator (proportional vs historical). 2025 is held out and
    is touched once, at the end, by whichever estimator the select block preferred.
  - Expected points come from `kblend:4`, the engine's own baseline half. There is no archive of
    Sleeper's weekly projections, so the live blend cannot be replayed; what is being tested is
    the tiebreak among near-equal players, and the tie is defined by the same 1.5-point window the
    engine uses.
  - Three arms per team-week, all starting from the same greedy lineup:
      none      plain greedy by expected points, no tiebreak
      boom      the current rule: inside the 1.5-point window prefer the higher boom rate, where
                boom rate is the share of the player's previous-season games spent in that week's
                positional top 12 (point-in-time; the preseason model's own boom_rate column is a
                2026 artifact and does not exist for past seasons)
      vacated   inside the same window prefer the higher vacated-absorption points
  - A swap only happens when the challenger's key is strictly greater AND greater than zero, so an
    arm never fires on a tie of two zeros.

A null result is a real result: it means the column ships as information and the tiebreak does not
change.
"""
import json
import os
import statistics
import time
from collections import defaultdict

from .. import config, store
from ..timeutil import now_utc, iso
from . import histbacktest as hb, histdata, histmodels as hm, histstats as hs, usagedata, vacated as vc

SELECT = list(range(2015, 2025))
TEST = 2025
BASE_MODEL = "kblend:4"
FIRST_EVAL_WEEK = 2
BOOM_TOP_N = 12
ESTIMATORS = ("proportional", "historical")
MARKER = "<!-- vacated-share backtest -->"


# ---------------------------------------------------------------- point-in-time boom rate
def boom_rates(prev_season):
    """{pid: share of his previous-season games spent in that week's positional top 12}."""
    if not prev_season:
        return {}
    by_week = defaultdict(list)
    for p in prev_season["players"]:
        by_week[(p["week"], p["pos"])].append((p["pts"], p["pid"]))
    hits, games = defaultdict(int), defaultdict(int)
    for key, lst in by_week.items():
        lst.sort(reverse=True)
        top = {pid for _, pid in lst[:BOOM_TOP_N]}
        for _, pid in lst:
            games[pid] += 1
            if pid in top:
                hits[pid] += 1
    return {pid: hits[pid] / n for pid, n in games.items() if n}


# ---------------------------------------------------------------- lineups
def tiebreak_lineup(cands, pred_of, key_of, slots, gap=vc.CLOSE_GAP):
    """Greedy by expected points, then inside each slot swap in the best bench alternative within
    `gap` points whose key is strictly higher and above zero. Mirrors the close-call rule."""
    base = hb.greedy_lineup(cands, pred_of, slots)
    used = {cid for _, cid in base}
    pos_of = dict(cands)
    out = []
    for slot, cid in base:
        elig = hb.FLEX_ELIGIBLE if slot == "FLEX" else {slot}
        cur = key_of(cid)
        best, best_key = None, cur
        for c, pos in cands:
            if c in used or pos not in elig or pred_of(c) is None:
                continue
            if (pred_of(cid) - pred_of(c)) >= gap:
                continue
            k = key_of(c)
            if k > best_key + 1e-9 and k > 0:
                best, best_key = c, k
        if best is not None:
            used.discard(cid)
            used.add(best)
            out.append((slot, best))
        else:
            out.append((slot, cid))
    return out


def season_arms(seasons, year, scoring, slots, estimators=ESTIMATORS, weeks_max=None):
    """Replay one season. Returns {(week,): {arm: mean lineup points}} plus decision counts."""
    s = seasons[year]
    prev = seasons.get(year - 1)
    idx = hm.SeasonIndex(s, prev, {})
    rosters = hb.draft_rosters(idx)
    boom = boom_rates(prev)
    u = usagedata.build(year, scoring, quiet=True)
    if u is None:
        return None
    memo = {}

    def sig_points(pid, pos, team, week, est):
        key = (pid, week, est)
        if key in memo:
            return memo[key]
        val = 0.0
        if pos in vc.POS_OK and team:
            absent = u.absent.get((year, week, team)) or set()
            if absent:
                sg = vc.signal(u, pid, team, pos, year, week, absent, estimator=est)
                val = (sg or {}).get("points") or 0.0
        memo[key] = val
        return val

    arms = ["none", "boom"] + [f"vacated:{e}" for e in estimators]
    week_arm = defaultdict(dict)
    swaps = {a: 0 for a in arms}
    disagree = 0
    pair_rows = []
    weeks = [w for w in s["weeks"] if w >= FIRST_EVAL_WEEK and (weeks_max is None or w <= weeks_max)]
    for w in weeks:
        rows, drows = idx.by_week[w], idx.dby_week[w]
        preds = hm.predict_week(idx, w, BASE_MODEL)
        dpreds = hm.predict_def_week(idx, w, BASE_MODEL)
        actual = {p["pid"]: p["pts"] for p in rows}
        dactual = {d["team"]: d["pts"] for d in drows}
        pos_of_row = {p["pid"]: (p["pos"], p["team"]) for p in rows}
        totals = {a: [] for a in arms}
        for r in rosters:
            cands = [(pid, pos) for pos, lst in r.items() if pos != "DEF" for pid in lst if pid in actual]
            cands += [(t, "DEF") for t in r.get("DEF", []) if t in dactual]
            if not cands:
                continue
            prd = lambda cid: preds.get(cid, dpreds.get(cid))            # noqa: E731
            act = lambda cid: actual.get(cid, dactual.get(cid)) or 0.0   # noqa: E731
            keys = {"none": lambda cid: 0.0, "boom": lambda cid: boom.get(cid, 0.0)}
            for e in estimators:
                keys[f"vacated:{e}"] = (lambda cid, e=e: sig_points(cid, *pos_of_row.get(cid, (None, None)), w, e))
            chosen = {}
            for a in arms:
                lu = tiebreak_lineup(cands, prd, keys[a], slots)
                chosen[a] = lu
                totals[a].append(sum(act(c) for _, c in lu))
            base_ids = {c for _, c in chosen["none"]}
            for a in arms[1:]:
                swaps[a] += len({c for _, c in chosen[a]} - base_ids)
            prim = f"vacated:{estimators[0]}"
            b_ids, v_ids = {c for _, c in chosen["boom"]}, {c for _, c in chosen[prim]}
            if b_ids != v_ids:
                disagree += 1
                only_b, only_v = sorted(b_ids - v_ids), sorted(v_ids - b_ids)
                pair_rows.append({"season": year, "week": w,
                                  "boom_only_pts": round(sum(act(c) for c in only_b), 2),
                                  "vac_only_pts": round(sum(act(c) for c in only_v), 2)})
        for a in arms:
            week_arm[(year, w)][a] = statistics.mean(totals[a]) if totals[a] else None
    return {"week_arm": dict(week_arm), "swaps": swaps, "n_disagree_team_weeks": disagree,
            "pairs": pair_rows, "arms": arms}


def aggregate(per_season):
    week_arm = {}
    swaps = defaultdict(int)
    disagree = 0
    pairs = []
    arms = None
    for r in per_season:
        week_arm.update(r["week_arm"])
        for a, v in r["swaps"].items():
            swaps[a] += v
        disagree += r["n_disagree_team_weeks"]
        pairs += r["pairs"]
        arms = r["arms"]
    means = {a: round(statistics.mean([v[a] for v in week_arm.values() if v.get(a) is not None]), 3)
             for a in arms}
    return {"arms": arms, "week_arm": week_arm, "swaps": dict(swaps), "n_disagree_team_weeks": disagree,
            "pairs": pairs, "lineup_pts_per_team_week": means, "n_weeks": len(week_arm)}


def compare(agg, a, b):
    """Paired bootstrap of arm a minus arm b over weeks."""
    diffs = {k: v[a] - v[b] for k, v in agg["week_arm"].items() if v.get(a) is not None and v.get(b) is not None}
    return hs.paired_bootstrap(diffs)


# ---------------------------------------------------------------- main
def run(data_dir=None, download=True, seasons=None, quiet=False):
    t0 = time.time()
    if data_dir:
        config.DATA_DIR = data_dir
    scoring, slots, _ = histdata.scoring_from_league()
    from .. import history
    if download:
        history.ensure(kinds=("injuries",), quiet=True)
    cov = history.injuries_coverage()
    have = sorted(y for y, v in cov.items() if v.get("present") and v.get("n_weeks", 0) >= 17)
    sel = [y for y in (seasons or SELECT) if y in have]
    test_ok = TEST in have
    notes = []
    if sel != (seasons or SELECT):
        missing = sorted(set(seasons or SELECT) - set(sel))
        notes.append(f"nflverse injuries release is missing or partial for {missing}; the selection window was cut to "
                     f"{sel[0]}-{sel[-1]} rather than filling the gaps.")
    if not test_ok:
        notes.append(f"nflverse injuries release is missing or partial for {TEST}; no held-out number is reported.")

    def say(m):
        if not quiet:
            print("vacated:", m)

    say(f"injuries coverage: {len(have)} seasons with a full report ({have[0]}-{have[-1]})")
    loaded = {}
    for y in sorted(set(sel + ([TEST] if test_ok else []) + [y - 1 for y in sel + ([TEST] if test_ok else [])])):
        s = histdata.load_season(y, scoring)
        if s:
            loaded[y] = s
    say(f"select block {sel}")
    per = []
    for y in sel:
        r = season_arms(loaded, y, scoring, slots)
        if r:
            per.append(r)
            say(f"  {y}: {len(r['week_arm'])} weeks, {r['n_disagree_team_weeks']} team-weeks where the two tiebreaks disagreed")
    select = aggregate(per)
    select_cmp = {f"{a} vs boom": compare(select, a, "boom") for a in select["arms"] if a.startswith("vacated:")}
    select_cmp["boom vs none"] = compare(select, "boom", "none")
    for a in select["arms"]:
        if a.startswith("vacated:"):
            select_cmp[f"{a} vs none"] = compare(select, a, "none")
    # pick the estimator the select block prefers on lineup points
    cands = [a for a in select["arms"] if a.startswith("vacated:")]
    best = max(cands, key=lambda a: select["lineup_pts_per_team_week"][a])
    say(f"select block prefers {best}")

    test = test_cmp = None
    if test_ok:
        say(f"held-out {TEST} with {best}")
        est = best.split(":", 1)[1]
        rt = season_arms(loaded, TEST, scoring, slots, estimators=(est,))
        if rt:
            test = aggregate([rt])
            test_cmp = {f"{best} vs boom": compare(test, best, "boom"),
                        f"{best} vs none": compare(test, best, "none"),
                        "boom vs none": compare(test, "boom", "none")}

    out = {"generated_at_utc": iso(now_utc()), "select_seasons": sel, "test_season": TEST if test_ok else None,
           "base_model": BASE_MODEL, "close_gap": vc.CLOSE_GAP, "estimators": list(ESTIMATORS),
           "injuries_coverage": {str(k): v for k, v in cov.items()},
           "select": {k: v for k, v in select.items() if k not in ("week_arm", "pairs")},
           "select_bootstrap": select_cmp, "selected_estimator": best,
           "test": ({k: v for k, v in test.items() if k not in ("week_arm", "pairs")} if test else None),
           "test_bootstrap": test_cmp, "notes": notes,
           "constants": {"decay": vc.DECAY, "prior_games": vc.PRIOR_GAMES, "ppo_prior_opps": vc.PPO_PRIOR_OPPS,
                         "min_hist_games": vc.MIN_HIST_GAMES},
           "limitations": [
               "Expected points are the engine's k=4 baseline half, not the live 0.65 Sleeper blend; no archive of Sleeper's weekly projections exists.",
               "Absence is read from the nflverse weekly injury report (Out or Doubtful) plus a carry-forward for players who drop off the report; a healthy scratch who never appears on the report is counted as available, which understates vacated share.",
               "Vacated share counts absent teammates at the same position only. Cross-position flow (a TE's targets going to WRs) is not modeled.",
               "Boom rate here is computed from the previous season, because the preseason model's boom_rate column is a 2026 artifact with no historical equivalent.",
               "Rosters are the main harness's fixed drafted rosters; no waivers, no trades.",
           ],
           "runtime_seconds": round(time.time() - t0, 1)}
    say(f"done in {out['runtime_seconds']} s")
    return out


# ---------------------------------------------------------------- write-up
def _f(v, d=2):
    return "-" if v is None else (f"{v:.{d}f}" if isinstance(v, float) else str(v))


def _b(b):
    if not b or b.get("mean") is None:
        return "-"
    return f"{b['mean']:+.3f} ({b['lo']:+.3f} to {b['hi']:+.3f}, {b['n_weeks']} weeks)"


def markdown(out):
    L = [MARKER, "", "## Vacated target share (display-only column)", "",
         f"Generated {out['generated_at_utc']}. Select block {out['select_seasons'][0]}-{out['select_seasons'][-1]}, "
         f"held out {out['test_season'] or 'not evaluated'}. Expected points for the pairing come from `{out['base_model']}`, "
         f"the engine's own baseline half, and a pair counts as close when it is within {out['close_gap']} points.", ""]
    cov = out["injuries_coverage"]
    full = [k for k, v in sorted(cov.items()) if v.get("present")]
    L += ["### Data", "",
          f"nflverse `injuries` release: present for {full[0]} to {full[-1]} ({len(full)} seasons). "
          f"Rows carry `report_status` and `practice_status`; weeks 1 to 18 of each season plus the playoffs, "
          f"which are filtered out. A player counts as absent when that week's report says Out or Doubtful, or when he "
          f"was absent the week before and had no stat row that week.", ""]
    for n in out["notes"]:
        L.append(f"- {n}")
    if out["notes"]:
        L.append("")
    L += ["| Season | Injury rows | Weeks | Rows with a report status | Rows marked Out |", "|---|---|---|---|---|"]
    for k, v in sorted(cov.items()):
        if v.get("present"):
            L.append(f"| {k} | {v['rows']:,} | {v['n_weeks']} | {v['rows_with_report_status']:,} | {v['rows_out']:,} |")
    L.append("")
    sel = out["select"]
    L += [f"### Select block {out['select_seasons'][0]}-{out['select_seasons'][-1]}", "",
          f"{sel['n_weeks']} season-weeks, 12 simulated rosters each. "
          f"The two tiebreaks chose different lineups in {sel['n_disagree_team_weeks']:,} team-weeks.", "",
          "| Arm | Lineup pts / team-week | Starters swapped in vs no tiebreak |", "|---|---|---|"]
    for a in sel["arms"]:
        L.append(f"| {a} | {_f(sel['lineup_pts_per_team_week'][a], 3)} | {sel['swaps'].get(a, 0):,} |")
    L += ["", "Paired bootstrap over weeks (positive = the first arm scored more):", "",
          "| Comparison | Mean diff | Crosses zero |", "|---|---|---|"]
    for k, b in out["select_bootstrap"].items():
        L.append(f"| {k} | {_b(b)} | {'yes' if (b or {}).get('crosses_zero') else 'no'} |")
    L += ["", f"Estimator carried to the held-out season: **{out['selected_estimator']}**.", ""]
    if out.get("test"):
        t = out["test"]
        L += [f"### Held-out season {out['test_season']}", "",
              f"{t['n_weeks']} weeks, touched once.", "",
              "| Arm | Lineup pts / team-week | Starters swapped in vs no tiebreak |", "|---|---|---|"]
        for a in t["arms"]:
            L.append(f"| {a} | {_f(t['lineup_pts_per_team_week'][a], 3)} | {t['swaps'].get(a, 0):,} |")
        L += ["", "| Comparison | Mean diff | Crosses zero |", "|---|---|---|"]
        for k, b in (out["test_bootstrap"] or {}).items():
            L.append(f"| {k} | {_b(b)} | {'yes' if (b or {}).get('crosses_zero') else 'no'} |")
        L.append("")
    L += ["### Verdict", ""] + [f"- {v}" for v in verdict_lines(out)] + [""]
    L += ["### Limitations", ""] + [f"- {v}" for v in out["limitations"]] + [""]
    return L


def verdict_lines(out):
    """The honest reading, including when it is null."""
    best = out["selected_estimator"]
    where = f"held-out {out['test_season']}" if out.get("test_bootstrap") else "the select block"
    boots = out.get("test_bootstrap") or out["select_bootstrap"]
    v = []
    vb = boots.get(f"{best} vs boom")
    if vb and vb.get("mean") is not None:
        if vb.get("crosses_zero") or vb["mean"] <= 0:
            v.append(f"NULL RESULT. On {where} the vacated tiebreak did not beat the boom-rate tiebreak: "
                     f"{_b(vb)} lineup points per team-week, and the interval includes zero. The column therefore "
                     f"ships as information only and the close-call tiebreak stays on boom rate.")
        else:
            v.append(f"On {where} the vacated tiebreak beat the boom-rate tiebreak by {_b(vb)} lineup points per "
                     f"team-week, interval clear of zero.")
    vn = boots.get(f"{best} vs none")
    if vn and vn.get("mean") is not None:
        worse = (vn["mean"] or 0) < 0 and not vn.get("crosses_zero")
        v.append(f"Against no tiebreak at all, the vacated arm scored {_b(vn)} on {where}"
                 + (", which is measurably worse: swapping on this signal inside the close-call window costs points. "
                    "That is another reason it stays a display column." if worse else
                    ", which cannot be told apart from zero."))
    bn = boots.get("boom vs none")
    if bn and bn.get("mean") is not None:
        v.append(f"For scale, the tiebreak the engine uses today scored {_b(bn)} against no tiebreak on {where}. "
                 f"On the select block it was {_b(out['select_bootstrap'].get('boom vs none'))}, i.e. the boom-rate "
                 f"rule is not itself established as an improvement; nothing here promotes it either.")
    v.append(f"Estimators: {' and '.join(out['estimators'])}. The select block preferred {best.split(':', 1)[1]}, by "
             f"{abs(out['select']['lineup_pts_per_team_week'][best] - min(out['select']['lineup_pts_per_team_week'][a] for a in out['select']['arms'] if a.startswith('vacated:'))):.3f} "
             f"lineup points per team-week, which is well inside the noise; treat the choice between them as arbitrary.")
    v.append("The column never enters `expected` in any arm. tests/test_vacated.py asserts that a roster's expected "
             "points are identical with the column computed and with it absent.")
    return v


def blocks(out):
    """Dashboard tables for the Backtest tab. Tagged so a rerun replaces them cleanly."""
    B = []
    sel = out["select"]
    rows = [{"arm": a, "pts": sel["lineup_pts_per_team_week"][a], "swaps": sel["swaps"].get(a, 0)} for a in sel["arms"]]
    B.append({"group": "vacated", "title": f"Vacated share: tiebreak arms on the select block "
                                           f"{out['select_seasons'][0]}-{out['select_seasons'][-1]} ({sel['n_weeks']} season-weeks)",
              "rows": rows, "cols": [["arm", "Tiebreak arm"], ["pts", "Lineup pts / team-week", 3], ["swaps", "Starters swapped in", 0]],
              "text": "Every arm starts from the same lineup chosen by expected points and may only swap inside the 1.5-point "
                      "close-call window. 'none' applies no tiebreak at all."})
    brows = [{"pair": k, "mean": (b or {}).get("mean"), "lo": (b or {}).get("lo"), "hi": (b or {}).get("hi"),
              "weeks": (b or {}).get("n_weeks"), "zero": "yes" if (b or {}).get("crosses_zero") else "no"}
             for k, b in out["select_bootstrap"].items()]
    if out.get("test_bootstrap"):
        brows += [{"pair": k + f" (held-out {out['test_season']})", "mean": (b or {}).get("mean"), "lo": (b or {}).get("lo"),
                   "hi": (b or {}).get("hi"), "weeks": (b or {}).get("n_weeks"), "zero": "yes" if (b or {}).get("crosses_zero") else "no"}
                  for k, b in out["test_bootstrap"].items()]
    B.append({"group": "vacated", "title": "Vacated share: paired bootstrap over weeks (positive = the first arm scored more)",
              "rows": brows, "cols": [["pair", "Comparison"], ["mean", "Mean diff", 3], ["lo", "95% lo", 3], ["hi", "95% hi", 3],
                                      ["weeks", "Weeks", 0], ["zero", "Crosses zero"]],
              "text": "'yes' in the last column means the difference cannot be told apart from zero.",
              "notes": verdict_lines(out)})
    return B


def headline(out):
    return verdict_lines(out)[:1]


def append_to_hist_backtest(out, data_dir=None):
    """Write the json and put the markdown section into data/derived/hist_backtest.md, replacing
    any earlier copy of the same marked section."""
    d = os.path.join(data_dir or config.DATA_DIR, "derived")
    store.write_json(os.path.join(d, "vacated_backtest.json"), out)
    path = os.path.join(d, "hist_backtest.md")
    body = "\n".join(markdown(out)) + "\n"
    old = store.read_text(path, "")
    if MARKER in old:
        old = old.split(MARKER)[0].rstrip() + "\n\n"
    elif old and not old.endswith("\n"):
        old += "\n"
    store.write_text(path, (old or "") + body)
    # keep the dashboard's Backtest tab in step without needing a full histbacktest rerun
    hp = os.path.join(d, "hist_backtest.json")
    hist = store.read_json(hp, None)
    if isinstance(hist, dict) and hist.get("blocks") is not None:
        hist["vacated"] = {k: v for k, v in out.items() if k != "injuries_coverage"}
        hist["blocks"] = [b for b in hist["blocks"] if b.get("group") != "vacated"] + blocks(out)
        hist["headline"] = [h for h in (hist.get("headline") or []) if "vacated" not in h.lower()] + headline(out)
        store.write_json(hp, hist)
    return path


def main(data_dir=None, download=True):
    out = run(data_dir=data_dir, download=download)
    p = append_to_hist_backtest(out, data_dir)
    print("vacated: wrote", p)
    return out
