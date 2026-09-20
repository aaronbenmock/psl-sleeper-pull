"""Historical backtest and evaluation harness (Phase B). Stdlib only. Run: python engine.py histbacktest

What it does, in order:
  1. Downloads / verifies the nflverse cache (engine.history) and builds season tables (histdata).
  2. THE GATE: reproduces Sleeper's real week-1 2026 PSL points. Offense must match within 0.1 for
     every matched player or the run stops here and writes the mismatch report.
  3. Splits seasons three ways: fit 2015-2019, select 2020-2024, held-out 2025. Descriptive
     statistics (B6.1 reliability, B6.2 persistence, B6.3 noise floor, B6.6 leaks, B6.7 role change)
     use fit + select only; 2025 is touched once, at the end, by the selected model and the baselines.
  4. Fits the volume coefficients and the recency decay on the fit block, evaluates every candidate
     configuration on the select block (MAE, RMSE, Spearman, lineup points captured in a simulated
     12-team league using the PSL roster slots), and picks the best by lineup points per team-week.
  5. Scores the pick against the current baseline on 2025 with a week-level paired bootstrap,
     calibration deciles and out-of-sample prediction-interval coverage.
  6. Leakage test (corrupt future weeks, assert byte-identical earlier predictions) and a
     determinism test (two runs, identical output).
  7. Writes data/derived/hist_backtest.json and hist_backtest.md; the dashboard's Backtest tab reads the json.

Limitation stated once here and in the findings: there is no archive of Sleeper's own weekly
projections, so nothing in this harness can tune w, the weight on Sleeper's number in the live blend.
It tunes the baseline half that Sleeper is blended against.
"""
import json
import math
import os
import statistics
import time
from collections import defaultdict

from .. import config, store
from ..timeutil import now_utc, iso
from .. import history
from . import histdata, histmodels as hm, histstats as hs

FIT = [2015, 2016, 2017, 2018, 2019]
SELECT = [2020, 2021, 2022, 2023, 2024]
TEST = 2025
FLEX_ELIGIBLE = {"RB", "WR", "TE"}
DRAFT_NEED = {"QB": 2, "RB": 4, "WR": 4, "TE": 2, "DEF": 2}
N_TEAMS = 12
FIRST_EVAL_WEEK = 2
STARTER_CUT = {"QB": 12, "RB": 30, "WR": 36, "TE": 12}     # top-N by prediction per week = a 12-team league's starters
REG_MIN_GAMES = 8                                          # "regulars" for the noise-floor comparison (same rule as B6.3)


# ------------------------------------------------------------------ candidates
def candidate_models(best_decay):
    a = best_decay
    m = ["naive"]
    m += [f"lastN:{n}" for n in (2, 3, 4, 5, 6)]
    m += [f"ewma:{x}" for x in sorted({0.1, 0.2, 0.3, 0.4, 0.5, a})]
    m += [f"kblend:{k}" for k in (1, 2, 4, 6, 8, 12)]
    m += [f"ewk:{a}:{k}" for k in (2, 4, 8)]
    m += [f"vol:{lam}:{k}" for lam in (0.5, 1.0) for k in (2, 4)]
    m += [f"vol:{lam}:{k}:{a}" for lam in (0.5, 1.0) for k in (2, 4)]
    m += [f"kblend:4+opp:{g}:4:0.2" for g in (0.5, 1.0)]
    m += [f"ewk:{a}:4+opp:{g}:4:0.2" for g in (0.5, 1.0)]
    m += [f"vol:0.5:4:{a}+opp:{g}:4:0.2" for g in (0.5, 1.0)]
    m += [f"vol:1.0:4:{a}+opp:{g}:4:0.2" for g in (0.5, 1.0)]
    return m


# ------------------------------------------------------------------ lineup simulation
def draft_rosters(idx, seed_order=None):
    """Snake draft 12 fixed rosters from prior-season ppg (value over replacement). Deterministic."""
    pool = []
    for pid, prior in idx.prior.items():
        pos = idx.pos_of.get(pid)
        if pos:
            pool.append((pid, pos, prior))
    for team, prior in idx.dprior.items():
        pool.append((team, "DEF", prior))
    by_pos = defaultdict(list)
    for pid, pos, v in pool:
        by_pos[pos].append((v, pid))
    repl = {}
    for pos, lst in by_pos.items():
        lst.sort(reverse=True)
        k = min(len(lst) - 1, N_TEAMS * DRAFT_NEED.get(pos, 1))
        repl[pos] = lst[k][0] if lst else 0.0
    avail = {pid: (pos, v - repl.get(pos, 0.0)) for pid, pos, v in pool}
    rosters = [defaultdict(list) for _ in range(N_TEAMS)]
    order = list(range(N_TEAMS))
    rounds = sum(DRAFT_NEED.values())
    for rnd in range(rounds):
        seq = order if rnd % 2 == 0 else order[::-1]
        for t in seq:
            need = {pos: DRAFT_NEED[pos] - len(rosters[t][pos]) for pos in DRAFT_NEED}
            best = None
            for pid, (pos, vor) in avail.items():
                if need.get(pos, 0) > 0 and (best is None or vor > best[0] or (vor == best[0] and pid < best[1])):
                    best = (vor, pid, pos)
            if best is None:
                continue
            rosters[t][best[2]].append(best[1])
            del avail[best[1]]
    return [dict(r) for r in rosters]


def greedy_lineup(cands, score_of, slots):
    """cands: list of (id, pos). Fills slots in order by score. Returns [(slot, id)]."""
    pool = sorted(cands, key=lambda c: -(score_of(c[0]) if score_of(c[0]) is not None else -1e9))
    used, out = set(), []
    for slot in slots:
        elig = FLEX_ELIGIBLE if slot == "FLEX" else {slot}
        for cid, pos in pool:
            if cid not in used and pos in elig and score_of(cid) is not None:
                used.add(cid)
                out.append((slot, cid))
                break
    return out


GAP_LABELS = ["QB", "RB", "WR", "TE", "DEF"]


def slot_points(chosen, actual_of, pos_of):
    """Points started, grouped by the player's position (FLEX decisions therefore show up inside RB/WR/TE).
    Grouping by position rather than by slot label avoids the artifact where the optimal lineup's FLEX
    holds a lower scorer than the chosen lineup's FLEX simply because the best players were slotted first."""
    out = {k: 0.0 for k in GAP_LABELS}
    for slot, cid in chosen:
        out[pos_of(cid)] += actual_of(cid) or 0.0
    return out, GAP_LABELS


def simulate_week(idx, week, preds, dpreds, rosters, slots, week_rows, dweek_rows):
    """One week for all 12 rosters. Returns list of team-week records."""
    actual = {p["pid"]: p["pts"] for p in week_rows}
    dactual = {d["team"]: d["pts"] for d in dweek_rows}
    recs = []
    for r in rosters:
        cands = [(pid, pos) for pos, lst in r.items() if pos != "DEF" for pid in lst if pid in actual]
        cands += [(t, "DEF") for t in r.get("DEF", []) if t in dactual]
        act = lambda cid: actual.get(cid, dactual.get(cid))  # noqa: E731
        prd = lambda cid: preds.get(cid, dpreds.get(cid))    # noqa: E731
        chosen = greedy_lineup(cands, prd, slots)
        optimal = greedy_lineup(cands, act, slots)
        pos_of = dict(cands)
        cp, labels = slot_points(chosen, act, pos_of.get)
        op, _ = slot_points(optimal, act, pos_of.get)
        # FLEX view: points from the 5 skill starters split into the 4 dedicated RB/WR slots (best 2 RB + best 2 WR
        # actually started) and the 2 FLEX slots (the rest); tells us whether the leak is the RB/WR core or the FLEX pick
        for lab, lu in (("chosen", chosen), ("optimal", optimal)):
            rb = sorted((act(c) or 0.0 for sl, c in lu if pos_of.get(c) == "RB"), reverse=True)
            wr = sorted((act(c) or 0.0 for sl, c in lu if pos_of.get(c) == "WR"), reverse=True)
            te = [act(c) or 0.0 for sl, c in lu if pos_of.get(c) == "TE"]
            core = sum(rb[:2]) + sum(wr[:2])
            flex = sum(rb[2:]) + sum(wr[2:]) + sum(te)
            (cp if lab == "chosen" else op)["RB/WR core"] = core
            (cp if lab == "chosen" else op)["FLEX picks"] = flex
        recs.append({"chosen_pts": round(sum(cp[k] for k in GAP_LABELS), 2), "optimal_pts": round(sum(op[k] for k in GAP_LABELS), 2),
                     "chosen": cp, "optimal": op, "labels": labels})
    return recs


# ------------------------------------------------------------------ evaluation
def eval_models(seasons_by_year, models, coefs, years, slots, keep_pairs=False, weeks_max=None):
    """Replay `years` for each model. Returns per-model aggregates and (optionally) raw per-week pairs."""
    res = {m: {"abs": [], "sq": [], "n": 0, "by_pos": defaultdict(lambda: {"abs": 0.0, "n": 0}), "starters": {"abs": 0.0, "n": 0, "bias": 0.0},
               "reg_by_pos": defaultdict(lambda: {"abs": 0.0, "n": 0}), "reg_week_pos": defaultdict(lambda: defaultdict(lambda: {"abs": 0.0, "n": 0})),
               "by_week": defaultdict(lambda: {"abs": 0.0, "n": 0}), "by_season": defaultdict(lambda: {"abs": 0.0, "n": 0}),
               "spearman_weeks": [], "lineup": [], "lineup_by_week": defaultdict(list), "pairs": [], "week_mae": {}, "week_lineup": {}}
           for m in models}
    for y in years:
        s = seasons_by_year[y]
        prev = seasons_by_year.get(y - 1)
        idx = hm.SeasonIndex(s, prev, coefs)
        rosters = draft_rosters(idx)
        regular = {pid for pid, g in idx.games.items() if len(g) >= REG_MIN_GAMES}     # diagnostic subset only, never used to predict
        dregular = {t for t, g in idx.dgames.items() if len(g) >= REG_MIN_GAMES}
        weeks = [w for w in s["weeks"] if w >= FIRST_EVAL_WEEK and (weeks_max is None or w <= weeks_max)]
        for w in weeks:
            rows = idx.by_week[w]
            drows = idx.dby_week[w]
            for m in models:
                preds = hm.predict_week(idx, w, m)
                dpreds = hm.predict_def_week(idx, w, m)
                R = res[m]
                abs_w, n_w = 0.0, 0
                pv, av = [], []
                ranked = defaultdict(list)
                for p in rows:
                    ranked[p["pos"]].append((preds[p["pid"]], p["pid"]))
                starters = set()
                for pos, lst in ranked.items():
                    lst.sort(reverse=True)
                    starters.update(pid for _, pid in lst[:STARTER_CUT.get(pos, 0)])
                for p in rows:
                    pr = preds[p["pid"]]
                    e = abs(pr - p["pts"])
                    if p["pid"] in starters:
                        R["starters"]["abs"] += e
                        R["starters"]["n"] += 1
                        R["starters"]["bias"] += p["pts"] - pr
                    if p["pid"] in regular:
                        R["reg_by_pos"][p["pos"]]["abs"] += e
                        R["reg_by_pos"][p["pos"]]["n"] += 1
                        R["reg_week_pos"][(y, w)][p["pos"]]["abs"] += e
                        R["reg_week_pos"][(y, w)][p["pos"]]["n"] += 1
                    R["abs"].append(e)
                    R["sq"].append(e * e)
                    R["n"] += 1
                    R["by_pos"][p["pos"]]["abs"] += e
                    R["by_pos"][p["pos"]]["n"] += 1
                    R["by_week"][w]["abs"] += e
                    R["by_week"][w]["n"] += 1
                    R["by_season"][y]["abs"] += e
                    R["by_season"][y]["n"] += 1
                    abs_w += e
                    n_w += 1
                    pv.append(pr)
                    av.append(p["pts"])
                    if keep_pairs:
                        R["pairs"].append((y, w, p["pos"], pr, p["pts"]))
                for d in drows:
                    pr = dpreds[d["team"]]
                    e = abs(pr - d["pts"])
                    R["by_pos"]["DEF"]["abs"] += e
                    R["by_pos"]["DEF"]["n"] += 1
                    if d["team"] in dregular:
                        R["reg_by_pos"]["DEF"]["abs"] += e
                        R["reg_by_pos"]["DEF"]["n"] += 1
                        R["reg_week_pos"][(y, w)]["DEF"]["abs"] += e
                        R["reg_week_pos"][(y, w)]["DEF"]["n"] += 1
                    if keep_pairs:
                        R["pairs"].append((y, w, "DEF", pr, d["pts"]))
                sp = hs.spearman(pv, av)
                if sp is not None:
                    R["spearman_weeks"].append(sp)
                R["week_mae"][(y, w)] = abs_w / n_w if n_w else None
                recs = simulate_week(idx, w, preds, dpreds, rosters, slots, rows, drows)
                R["lineup"].extend(recs)
                R["lineup_by_week"][w].extend(recs)
                R["week_lineup"][(y, w)] = statistics.mean(r["chosen_pts"] for r in recs)
    return res


def summarize(R):
    n = R["n"]
    lu = R["lineup"]
    opt = sum(r["optimal_pts"] for r in lu)
    ch = sum(r["chosen_pts"] for r in lu)
    st = R["starters"]
    return {"n": n, "mae": round(sum(R["abs"]) / n, 3) if n else None,
            "starters_mae": round(st["abs"] / st["n"], 3) if st["n"] else None, "starters_bias": round(st["bias"] / st["n"], 3) if st["n"] else None, "starters_n": st["n"],
            "rmse": round(math.sqrt(sum(R["sq"]) / n), 3) if n else None,
            "spearman_mean_week": round(statistics.mean(R["spearman_weeks"]), 3) if R["spearman_weeks"] else None,
            "n_weeks": len(R["spearman_weeks"]),
            "lineup_pts_per_team_week": round(ch / len(lu), 2) if lu else None,
            "optimal_pts_per_team_week": round(opt / len(lu), 2) if lu else None,
            "pct_of_optimal": round(100 * ch / opt, 1) if opt else None, "n_team_weeks": len(lu),
            "mae_by_pos": {p: {"mae": round(v["abs"] / v["n"], 3), "n": v["n"]} for p, v in sorted(R["by_pos"].items()) if v["n"]},
            "reg_mae_by_pos": {p: {"mae": round(v["abs"] / v["n"], 3), "n": v["n"]} for p, v in sorted(R["reg_by_pos"].items()) if v["n"]},
            "mae_by_week": {w: {"mae": round(v["abs"] / v["n"], 3), "n": v["n"]} for w, v in sorted(R["by_week"].items()) if v["n"]},
            "mae_by_season": {y: {"mae": round(v["abs"] / v["n"], 3), "n": v["n"]} for y, v in sorted(R["by_season"].items()) if v["n"]},
            "lineup_by_week": {w: round(statistics.mean(r["chosen_pts"] for r in recs), 2) for w, recs in sorted(R["lineup_by_week"].items())}}


# ------------------------------------------------------------------ leakage + determinism
def corrupt_future(season, after_week, factor=1000.0):
    """Copy of a season table with every stat from weeks > after_week multiplied by an absurd factor."""
    s = json.loads(json.dumps(season))
    for p in s["players"]:
        if p["week"] > after_week:
            for k, v in p.items():
                if isinstance(v, (int, float)) and k != "week":
                    p[k] = v * factor + 999
    for d in s["defense"]:
        if d["week"] > after_week:
            d["pts"] = d["pts"] * factor + 999
            d["line"] = {k: (v * factor + 999 if isinstance(v, (int, float)) else v) for k, v in d["line"].items()}
    return s


def leakage_test(seasons_by_year, models, coefs, year, after_week):
    """Predictions for weeks <= after_week must be byte-identical when weeks > after_week are corrupted."""
    s = seasons_by_year[year]
    prev = seasons_by_year.get(year - 1)
    clean = hm.SeasonIndex(s, prev, coefs)
    dirty = hm.SeasonIndex(corrupt_future(s, after_week), prev, coefs)
    weeks = [w for w in s["weeks"] if FIRST_EVAL_WEEK <= w <= after_week]
    checked, leaks = 0, []
    for m in models:
        for w in weeks:
            a = json.dumps([hm.predict_week(clean, w, m), hm.predict_def_week(clean, w, m)], sort_keys=True)
            b = json.dumps([hm.predict_week(dirty, w, m), hm.predict_def_week(dirty, w, m)], sort_keys=True)
            checked += 1
            if a != b:
                leaks.append({"model": m, "week": w})
    # sanity: a later week MUST differ, otherwise the corruption did nothing
    w_after = after_week + 2
    control_differs = None
    if w_after in s["weeks"]:
        a = json.dumps(hm.predict_week(clean, w_after, models[0]), sort_keys=True)
        b = json.dumps(hm.predict_week(dirty, w_after, models[0]), sort_keys=True)
        control_differs = a != b
    return {"season": year, "corrupted_after_week": after_week, "models": len(models), "week_model_pairs_checked": checked,
            "leaks": leaks, "passed": not leaks and control_differs is True, "control_week_differs": control_differs}


# ------------------------------------------------------------------ main
def run(data_dir=None, download=True, quick=False):
    t0 = time.time()
    if data_dir:
        config.DATA_DIR = data_dir
    scoring, slots, league = histdata.scoring_from_league()
    log = []

    def say(msg):
        log.append(msg)
        print("histbacktest:", msg)

    if download:
        history.ensure(quiet=True)
    # ---- gate
    gate = histdata.gate()
    say(f"gate: offense {gate.get('n_compared')} compared, {gate.get('n_mismatch')} mismatches; "
        f"DEF {gate.get('def', {}).get('n')} compared, {gate.get('def', {}).get('n_mismatch')} mismatches")
    out = {"generated_at_utc": iso(now_utc()), "gate": gate, "scoring_settings_read": len(scoring), "slots": slots}
    if not gate.get("ok"):
        out["status"] = "STOPPED AT GATE"
        _write(out, log)
        raise RuntimeError("histbacktest stopped: scoring gate failed; see data/derived/hist_backtest.json")

    # ---- seasons
    years = list(range(2014, 2026))
    seasons = {}
    for y in years:
        s = histdata.load_season(y, scoring)
        if s:
            seasons[y] = s
    fit = [seasons[y] for y in FIT if y in seasons]
    sel = [seasons[y] for y in SELECT if y in seasons]
    desc = fit + sel
    n_pw = sum(len(s["players"]) for s in desc + [seasons[TEST]])
    n_dw = sum(len(s["defense"]) for s in desc + [seasons[TEST]])
    say(f"seasons loaded {sorted(seasons)}; offensive player-weeks 2015-2025 {n_pw:,}, defense-weeks {n_dw:,}")
    out["scope"] = {"fit_seasons": FIT, "select_seasons": SELECT, "test_season": TEST, "player_weeks_2015_2025": n_pw,
                    "defense_weeks_2015_2025": n_dw, "first_eval_week": FIRST_EVAL_WEEK,
                    "positions": ["QB", "RB", "WR", "TE", "DEF"], "def_included": True,
                    "def_note": "DEF scored from play-by-play including three-and-outs and fourth-down stops; all 32 week-1 2026 defenses matched Sleeper exactly."}

    # ---- descriptive statistics (fit + select only)
    say("B6.1 split-half reliability")
    out["reliability"] = hs.split_half(desc, min_games=10)
    say("B6.2 persistence")
    out["persistence"] = hs.persistence(fit if quick else desc)
    ppg_rows = [r for r in out["persistence"] if r["stat"] == "ppg"]
    # decay for the models: fitted on the fit block only (selection discipline)
    fit_pers = hs.persistence(fit, max_lag=1) if not quick else out["persistence"]
    dec = [r["best_decay"] for r in fit_pers if r["stat"] == "ppg" and r["best_decay"] is not None]
    best_decay = round(statistics.median(dec), 2) if dec else 0.3
    out["best_decay_fit_block"] = best_decay
    say(f"B6.3 noise floor (decay from fit block = {best_decay})")
    out["noise_floor"] = hs.noise_floor(desc)
    coefs = hm.fit_volume_coefs(fit)
    out["volume_coefs"] = {pos: {"intercept": round(c[0], 3), **{f: round(c[i + 1], 3) for i, f in enumerate(hm.FEATS)}} for pos, c in coefs.items()}

    # ---- candidates on the select block
    models = candidate_models(best_decay)
    say(f"evaluating {len(models)} configurations on the select block {SELECT}")
    sel_res = eval_models(seasons, models, coefs, SELECT, slots)
    table = []
    for m in models:
        sm = summarize(sel_res[m])
        sm["model"] = m
        table.append(sm)
    table.sort(key=lambda r: (-(r["lineup_pts_per_team_week"] or 0), r["mae"] or 99))
    out["select_table"] = table
    out["n_configurations"] = len(models)
    best = table[0]["model"]
    best_mae = min(table, key=lambda r: r["mae"] or 99)["model"]
    say(f"select block: best by lineup points = {best}; best by MAE = {best_mae}")
    out["selected"] = {"by_lineup": best, "by_mae": best_mae}

    # ---- held-out season
    finalists = ["naive", "kblend:4", best]
    if best_mae not in finalists:
        finalists.append(best_mae)
    say(f"held-out {TEST}: {finalists}")
    test_res = eval_models(seasons, finalists, coefs, [TEST], slots, keep_pairs=True)
    out["test"] = {m: summarize(test_res[m]) for m in finalists}
    # paired bootstraps vs the current baseline (naive) and vs the engine's k=4 baseline half
    boots = {}
    for ref in ("naive", "kblend:4"):
        for m in finalists:
            if m == ref:
                continue
            mae_d = {k: test_res[m]["week_mae"][k] - test_res[ref]["week_mae"][k] for k in test_res[m]["week_mae"]}
            lu_d = {k: test_res[m]["week_lineup"][k] - test_res[ref]["week_lineup"][k] for k in test_res[m]["week_lineup"]}
            boots[f"{m} vs {ref}"] = {"mae_diff": hs.paired_bootstrap(mae_d), "lineup_diff": hs.paired_bootstrap(lu_d)}
    out["bootstrap"] = boots
    # gap closed vs the noise floor, per position, for each finalist: naive, model and floor all measured on the
    # same population (players with 8+ games in the held-out season) so the percentages are comparable
    test_floor = hs.noise_floor([seasons[TEST]], min_games=REG_MIN_GAMES)
    out["noise_floor_test_season"] = test_floor
    gaps = {}
    for m in finalists:
        gaps[m] = {}
        for pos, v in out["test"][m]["reg_mae_by_pos"].items():
            base = out["test"]["naive"]["reg_mae_by_pos"].get(pos, {}).get("mae")
            floor = (test_floor.get(pos) or {}).get("floor_mae_known_mean")
            if base and floor:
                gaps[m][pos] = {"mae": v["mae"], "naive_mae": base, "floor": floor, "gap_total": round(base - floor, 3),
                                "gap_closed_pct": round(100 * (base - v["mae"]) / (base - floor), 1) if base > floor else None, "n": v["n"]}
    out["gap_closed"] = gaps
    # per-position week-level bootstraps vs the engine's k=4 baseline half (regulars), to locate any real gain
    pos_boots = {}
    for m in finalists:
        if m == "kblend:4":
            continue
        pos_boots[m] = {}
        for pos in ("QB", "RB", "WR", "TE", "DEF"):
            diffs = {}
            for key, byp in test_res[m]["reg_week_pos"].items():
                a, b = byp.get(pos), test_res["kblend:4"]["reg_week_pos"][key].get(pos)
                if a and b and a["n"] and b["n"]:
                    diffs[key] = a["abs"] / a["n"] - b["abs"] / b["n"]
            pos_boots[m][pos] = hs.paired_bootstrap(diffs)
    out["bootstrap_by_pos_vs_k4"] = pos_boots
    # calibration on the held-out season for the selected model and naive
    cal = {}
    for m in finalists:
        pairs = [(pr, a) for (_, _, pos, pr, a) in test_res[m]["pairs"] if pos != "DEF"]
        cal[m] = hs.calibration(pairs)
    out["calibration"] = cal
    # prediction intervals: fit on the select block for the selected model, test on 2025
    sel_pairs_res = eval_models(seasons, [best], coefs, SELECT, slots, keep_pairs=True)
    by_pos_fit = defaultdict(list)
    for (_, _, pos, pr, a) in sel_pairs_res[best]["pairs"]:
        by_pos_fit[pos].append((pr, a))
    intervals = hs.fit_intervals(by_pos_fit, 0.8)
    by_pos_test = defaultdict(list)
    for (_, _, pos, pr, a) in test_res[best]["pairs"]:
        by_pos_test[pos].append((pr, a))
    out["intervals"] = {"model": best, "level": 0.8, "fit_on": SELECT, "coverage_on_test": hs.test_intervals(intervals, by_pos_test), "table": intervals}

    # ---- B6.6 where the losses are (select block, typical manager = naive lineup)
    say("B6.6 slot gaps")
    lineup_rows = sel_res["naive"]["lineup"]
    out["slot_gaps"] = {"manager_rule": "naive (start by season average to date; prior-season ppg in week 1)",
                        "seasons": SELECT, **hs.slot_gaps(lineup_rows, GAP_LABELS)}
    out["slot_gaps_flex_view"] = hs.slot_gaps(lineup_rows, ["QB", "RB/WR core", "FLEX picks", "DEF"])
    lineup_rows_b = sel_res[best]["lineup"]
    out["slot_gaps_selected"] = {"manager_rule": best, **hs.slot_gaps(lineup_rows_b, GAP_LABELS)}

    # ---- B6.7 role change (stretch)
    say("B6.7 role change")
    out["role_change"] = [hs.role_change(desc, "tgt_share_calc", ("WR", "TE"), jump=0.08),
                          hs.role_change(desc, "car_share", ("RB",), jump=0.15),
                          hs.role_change(desc, "tgt_share_calc", ("RB",), jump=0.06)]

    # ---- leakage + determinism
    say("leakage test")
    out["leakage_test"] = leakage_test(seasons, finalists, coefs, TEST, after_week=9)
    say("determinism test")
    r1 = json.dumps({m: summarize(test_res[m]) for m in finalists}, sort_keys=True)
    test_res2 = eval_models(seasons, finalists, coefs, [TEST], slots)
    r2 = json.dumps({m: summarize(test_res2[m]) for m in finalists}, sort_keys=True)
    out["determinism_test"] = {"passed": r1 == r2, "bytes": len(r1)}
    out["limitations"] = [
        "No archive of Sleeper's weekly projections exists, so this harness cannot tune w, the weight on Sleeper's number in the live blend; it tunes only the baseline half that Sleeper is blended against.",
        "Rosters in the lineup simulation are fixed for the season (drafted from prior-season points per game); no waivers or trades, and rookies with no prior season are not drafted.",
        "Only players with a stat row in a week are eligible for that week's lineup, which is how Sleeper treats ruled-out players but assumes the manager knew every inactive in advance.",
        "Week 1 is not evaluated (no in-season data); every model falls back to the prior-season number there.",
        "Injury status, weather, Vegas totals and depth-chart news are not in the data.",
    ]
    # ---- the vacated-share column's own backtest, written into the same file
    say("vacated-share tiebreak backtest")
    try:
        from . import histvacated
        out["vacated_full"] = histvacated.run(download=download, quiet=True)
    except Exception as e:  # noqa: BLE001  a failure here must not lose the main run
        say(f"vacated backtest skipped: {e}")
    out["status"] = "OK"
    out["runtime_seconds"] = round(time.time() - t0, 1)
    say(f"done in {out['runtime_seconds']} s")
    _write(out, log)
    return out


# ------------------------------------------------------------------ outputs
def _fmt(v, d=2):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{d}f}"
    return str(v)


def _write(out, log):
    out["log"] = log
    d = os.path.join(config.DATA_DIR, "derived")
    blocks, headline = [], []
    md = ["# Historical backtest (nflverse 2015-2025, PSL scoring)", "", f"Generated {out['generated_at_utc']}. Status: {out.get('status')}.", ""]
    g = out.get("gate") or {}
    md += ["## Scoring gate (week 1, 2026)", "",
           f"Offense: {g.get('n_compared')} players compared, {g.get('n_mismatch')} outside 0.1. DEF: {(g.get('def') or {}).get('n')} compared, {(g.get('def') or {}).get('n_mismatch')} outside 0.1.", ""]
    headline.append(f"Scoring gate: {g.get('n_compared')} offensive players and {(g.get('def') or {}).get('n')} defenses reproduced Sleeper's week-1 2026 points, {g.get('n_mismatch')} mismatches.")
    if g.get("mismatches"):
        md += ["| Player | Team | Pos | Sleeper | Ours | Diff |", "|---|---|---|---|---|---|"]
        md += [f"| {m['name']} | {m['team']} | {m['pos']} | {m['sleeper']} | {m['ours']} | {m['diff']} |" for m in g["mismatches"]]
        md.append("")
    if out.get("status") != "OK":
        store.write_json(os.path.join(d, "hist_backtest.json"), out)
        store.write_text(os.path.join(d, "hist_backtest.md"), "\n".join(md) + "\n")
        return
    sc = out["scope"]
    scope_line = (f"{sc['player_weeks_2015_2025']:,} offensive player-weeks and {sc['defense_weeks_2015_2025']:,} defense-weeks, seasons 2015-2025. "
                  f"Fit {sc['fit_seasons'][0]}-{sc['fit_seasons'][-1]}, select {sc['select_seasons'][0]}-{sc['select_seasons'][-1]}, held-out {sc['test_season']}. "
                  f"{out['n_configurations']} configurations tried.")
    md += ["## Scope", "", scope_line, ""]
    # headline: winner on the held-out season
    best = out["selected"]["by_lineup"]
    t = out["test"]
    b_naive = out["bootstrap"].get(f"{best} vs naive", {})
    b_k4 = out["bootstrap"].get(f"{best} vs kblend:4", {})
    lu = b_naive.get("lineup_diff") or {}
    md += ["## Held-out season " + str(sc["test_season"]), "",
           "| Model | n | MAE (all) | MAE (starter-caliber) | n starters | Bias (starters) | RMSE | Spearman (mean/week) | Lineup pts / team-week | % of optimal |", "|---|---|---|---|---|---|---|---|---|---|"]
    rows = []
    for m, s in t.items():
        md.append(f"| {m} | {s['n']:,} | {_fmt(s['mae'])} | {_fmt(s['starters_mae'])} | {s['starters_n']:,} | {_fmt(s['starters_bias'])} | {_fmt(s['rmse'])} | {_fmt(s['spearman_mean_week'], 3)} | {_fmt(s['lineup_pts_per_team_week'])} | {_fmt(s['pct_of_optimal'], 1)} |")
        rows.append({"model": m, "n": s["n"], "mae": s["mae"], "smae": s["starters_mae"], "sn": s["starters_n"], "rmse": s["rmse"], "spearman": s["spearman_mean_week"], "lineup": s["lineup_pts_per_team_week"], "pct_opt": s["pct_of_optimal"]})
    md += ["", "Starter-caliber = the top 12 QB, 30 RB, 36 WR and 12 TE by that model's own prediction each week (what a 12-team league starts). MAE (all) covers every player with a stat row, most of whom score under 5.", ""]
    blocks.append({"title": f"Held-out season {sc['test_season']} (nothing here was used for selection)", "rows": rows,
                   "cols": [["model", "Model"], ["n", "n", 0], ["mae", "MAE all", 2], ["smae", "MAE starters", 2], ["sn", "n starters", 0], ["rmse", "RMSE", 2], ["spearman", "Spearman", 3], ["lineup", "Lineup pts / team-wk", 2], ["pct_opt", "% optimal", 1]],
                   "text": "Starter-caliber = top 12 QB / 30 RB / 36 WR / 12 TE by the model's own prediction each week."})
    verdict = []
    for label, b in (("naive baseline", b_naive), ("engine's k=4 baseline half", b_k4)):
        ld, md_ = b.get("lineup_diff") or {}, b.get("mae_diff") or {}
        if ld.get("mean") is not None:
            won = "did NOT beat" if ld.get("crosses_zero") or (ld.get("mean") or 0) <= 0 else "beat"
            verdict.append(f"{best} {won} the {label} on lineup points: {ld['mean']:+.2f} per team-week, 95% interval {ld['lo']:+.2f} to {ld['hi']:+.2f} over {ld['n_weeks']} weeks"
                           + (f"; MAE {md_['mean']:+.3f} ({md_['lo']:+.3f} to {md_['hi']:+.3f})" if md_.get("mean") is not None else "") + ".")
    headline += verdict
    md += ["### Paired bootstrap (weeks resampled, 4000 draws)", ""] + [f"- {v}" for v in verdict] + [""]
    brows = []
    for k, b in out["bootstrap"].items():
        for kind in ("lineup_diff", "mae_diff"):
            x = b[kind]
            brows.append({"pair": k, "metric": "lineup pts / team-week" if kind == "lineup_diff" else "MAE", "mean": x.get("mean"), "lo": x.get("lo"), "hi": x.get("hi"), "weeks": x.get("n_weeks"), "zero": "yes" if x.get("crosses_zero") else "no"})
    blocks.append({"title": "Paired bootstrap on the held-out season (positive = first model better on lineup points, worse on MAE)", "rows": brows,
                   "cols": [["pair", "Comparison"], ["metric", "Metric"], ["mean", "Mean diff", 3], ["lo", "95% lo", 3], ["hi", "95% hi", 3], ["weeks", "Weeks", 0], ["zero", "Crosses zero"]]})
    # gap closed
    md += ["### Gap to the noise floor closed (held-out season, players with 8+ games, MAE)", "",
           "Naive, model and floor are all measured on the same players (8 or more games in 2025). Floor = the MAE a model would have if it knew each player's true 2025 weekly mean.", "",
           "| Model | Pos | MAE | Naive MAE | Floor | Naive-to-floor gap | Gap closed | n |", "|---|---|---|---|---|---|---|---|"]
    grows = []
    for m, byp in out["gap_closed"].items():
        for pos, v in byp.items():
            md.append(f"| {m} | {pos} | {_fmt(v['mae'])} | {_fmt(v['naive_mae'])} | {_fmt(v['floor'])} | {_fmt(v['gap_total'])} | {_fmt(v['gap_closed_pct'], 1)}% | {v['n']:,} |")
            grows.append({"model": m, "pos": pos, "mae": v["mae"], "naive": v["naive_mae"], "floor": v["floor"], "closed": v["gap_closed_pct"], "n": v["n"]})
    md.append("")
    blocks.append({"title": "Share of the naive-to-floor gap each model closed (held-out season, 8+ game players)", "rows": grows,
                   "cols": [["model", "Model"], ["pos", "Pos"], ["mae", "MAE", 2], ["naive", "Naive MAE", 2], ["floor", "Floor", 2], ["closed", "Gap closed %", 1], ["n", "n", 0]],
                   "text": "Floor = MAE a model would have if it knew every player's true weekly mean (within-player week-to-week noise). 100% would mean the model reached that floor."})
    md += ["### Per-position paired bootstrap vs the engine's k=4 baseline half (held-out season, 8+ game players, weekly MAE difference; negative = better)", "",
           "| Model | Pos | Mean diff | 95% low | 95% high | Weeks | Crosses zero |", "|---|---|---|---|---|---|---|"]
    pb_rows = []
    for m, byp in out["bootstrap_by_pos_vs_k4"].items():
        for pos, b in byp.items():
            md.append(f"| {m} | {pos} | {_fmt(b.get('mean'), 3)} | {_fmt(b.get('lo'), 3)} | {_fmt(b.get('hi'), 3)} | {b.get('n_weeks')} | {'yes' if b.get('crosses_zero') else 'no'} |")
            pb_rows.append({"model": m, "pos": pos, "mean": b.get("mean"), "lo": b.get("lo"), "hi": b.get("hi"), "weeks": b.get("n_weeks"), "zero": "yes" if b.get("crosses_zero") else "no"})
    md.append("")
    blocks.append({"title": "Per-position bootstrap vs the k=4 baseline half (weekly MAE difference; negative = better; 'no' in the last column = a real difference)", "rows": pb_rows,
                   "cols": [["model", "Model"], ["pos", "Pos"], ["mean", "Mean diff", 3], ["lo", "95% lo", 3], ["hi", "95% hi", 3], ["weeks", "Weeks", 0], ["zero", "Crosses zero"]]})
    # select table
    md += [f"## Select block {sc['select_seasons'][0]}-{sc['select_seasons'][-1]}: all {out['n_configurations']} configurations", "",
           "| Model | n | MAE (all) | MAE (starters) | RMSE | Spearman | Lineup pts / team-week | % optimal |", "|---|---|---|---|---|---|---|---|"]
    srows = []
    for r in out["select_table"]:
        md.append(f"| {r['model']} | {r['n']:,} | {_fmt(r['mae'])} | {_fmt(r['starters_mae'])} | {_fmt(r['rmse'])} | {_fmt(r['spearman_mean_week'], 3)} | {_fmt(r['lineup_pts_per_team_week'])} | {_fmt(r['pct_of_optimal'], 1)} |")
        srows.append({"model": r["model"], "n": r["n"], "mae": r["mae"], "smae": r["starters_mae"], "spearman": r["spearman_mean_week"], "lineup": r["lineup_pts_per_team_week"], "pct_opt": r["pct_of_optimal"]})
    md.append("")
    blocks.append({"title": f"Select block ({sc['select_seasons'][0]}-{sc['select_seasons'][-1]}): every configuration, ranked by lineup points", "rows": srows,
                   "cols": [["model", "Model"], ["n", "n", 0], ["mae", "MAE all", 2], ["smae", "MAE starters", 2], ["spearman", "Spearman", 3], ["lineup", "Lineup pts", 2], ["pct_opt", "% optimal", 1]]})
    # by position / week / season for naive and best on test
    md += ["### MAE by position, held-out season", "", "| Model | " + " | ".join(f"{p}" for p in ("QB", "RB", "WR", "TE", "DEF")) + " |", "|---|---|---|---|---|---|"]
    for m, s in t.items():
        md.append(f"| {m} | " + " | ".join(f"{_fmt((s['mae_by_pos'].get(p) or {}).get('mae'))} (n={(s['mae_by_pos'].get(p) or {}).get('n', 0)})" for p in ("QB", "RB", "WR", "TE", "DEF")) + " |")
    md += ["", "### MAE by week of season, held-out season", "", "| Week | " + " | ".join(t.keys()) + " |", "|---|" + "---|" * len(t)]
    wk_all = sorted({w for s in t.values() for w in s["mae_by_week"]})
    for w in wk_all:
        md.append(f"| {w} | " + " | ".join(f"{_fmt((s['mae_by_week'].get(w) or {}).get('mae'))} (n={(s['mae_by_week'].get(w) or {}).get('n', 0)})" for s in t.values()) + " |")
    md += ["", "### MAE by season, select block (naive vs selected)", "", "| Season | naive | " + best + " |", "|---|---|---|"]
    st = {r["model"]: r for r in out["select_table"]}
    for y in sc["select_seasons"]:
        a, b = st["naive"]["mae_by_season"].get(y) or {}, st[best]["mae_by_season"].get(y) or {}
        md.append(f"| {y} | {_fmt(a.get('mae'))} (n={a.get('n', 0):,}) | {_fmt(b.get('mae'))} (n={b.get('n', 0):,}) |")
    md.append("")
    # reliability
    md += ["## B6.1 Split-half reliability (odd vs even weeks, Spearman-Brown corrected; players with 10+ games; 2015-2024)", "",
           "| Stat | Pos | r (corrected) | r (half) | Player-seasons | Seasons | r by season (min to max) |", "|---|---|---|---|---|---|---|"]
    rrows = []
    for r in out["reliability"]:
        md.append(f"| {r['stat']} | {r['pos']} | {_fmt(r['r_spearman_brown'], 3)} | {_fmt(r['r_half'], 3)} | {r['n_player_seasons']} | {r['seasons']} | {_fmt(r['r_by_season_min'], 2)} to {_fmt(r['r_by_season_max'], 2)} |")
        rrows.append({"stat": r["stat"], "pos": r["pos"], "r": r["r_spearman_brown"], "n": r["n_player_seasons"]})
    md.append("")
    blocks.append({"title": "B6.1 Reliability of each stat (split-half, Spearman-Brown corrected, 10+ games, 2015-2024)", "rows": rrows,
                   "cols": [["stat", "Stat"], ["pos", "Pos"], ["r", "Reliability", 3], ["n", "Player-seasons", 0]],
                   "text": "1.0 = a player's odd weeks predict his even weeks perfectly; 0 = pure noise."})
    # persistence
    md += ["## B6.2 Persistence (autocorrelation by lag, best simple window and best decay for predicting the next game; 8+ games)", "",
           "| Stat | Pos | lag1 | lag2 | lag3 | lag4 | lag5 | lag6 | n (lag 1) | Best window | Best decay |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    prows = []
    for r in out["persistence"]:
        ac = r["autocorr"]
        md.append(f"| {r['stat']} | {r['pos']} | " + " | ".join(_fmt(ac.get(L), 3) for L in range(1, 7)) + f" | {r['n_pairs_lag1']:,} | {r['best_window']} | {r['best_decay']} |")
        prows.append({"stat": r["stat"], "pos": r["pos"], "l1": ac.get(1), "l3": ac.get(3), "l6": ac.get(6), "n": r["n_pairs_lag1"], "win": r["best_window"], "dec": r["best_decay"]})
    md += ["", f"Decay used by the recency models (median of the ppg best-decay across positions on the fit block): {out['best_decay_fit_block']}.", ""]
    blocks.append({"title": "B6.2 Persistence: autocorrelation at lags 1, 3, 6 and the window that best predicts next game", "rows": prows,
                   "cols": [["stat", "Stat"], ["pos", "Pos"], ["l1", "Lag 1", 3], ["l3", "Lag 3", 3], ["l6", "Lag 6", 3], ["n", "n", 0], ["win", "Best window (games)", 0], ["dec", "Best decay", 2]]})
    # noise floor
    md += ["## B6.3 Noise floor (players with 8+ games, 2015-2024)", "", "| Pos | Player-seasons | Player-weeks | Total var | Between-player var | Within-player var | Share predictable | Floor MAE (known mean) | Floor RMSE |", "|---|---|---|---|---|---|---|---|---|"]
    nrows = []
    for pos, v in out["noise_floor"].items():
        md.append(f"| {pos} | {v['n_player_seasons']} | {v['n_player_weeks']:,} | {v['total_var']} | {v['between_player_var']} | {v['within_player_var']} | {_fmt(v['share_predictable'], 3)} | {v['floor_mae_known_mean']} | {v['floor_rmse_known_mean']} |")
        nrows.append({"pos": pos, "n": v["n_player_weeks"], "share": v["share_predictable"], "floor": v["floor_mae_known_mean"]})
    md.append("")
    blocks.append({"title": "B6.3 Noise floor: how much of weekly scoring is predictable at all", "rows": nrows,
                   "cols": [["pos", "Pos"], ["n", "Player-weeks", 0], ["share", "Share of variance between players", 3], ["floor", "Floor MAE", 2]],
                   "text": "Share predictable = between-player variance / total. Floor MAE = the error left even if every player's true mean were known."})
    # calibration
    md += ["## B6.4 Calibration on the held-out season", ""]
    crows = []
    for m, c in out["calibration"].items():
        if not c:
            continue
        md += [f"### {m}: slope of actual on predicted = {c['slope_actual_on_pred']} (intercept {c['intercept']}, r = {c['r']}, n = {c['n']:,})", "",
               "| Decile | n | Mean predicted | Mean actual |", "|---|---|---|---|"]
        for b in c["bins"]:
            md.append(f"| {b['decile']} | {b['n']} | {b['mean_pred']} | {b['mean_actual']} |")
        md.append("")
        crows.append({"model": m, "slope": c["slope_actual_on_pred"], "intercept": c["intercept"], "r": c["r"], "n": c["n"], "top": f"{c['bins'][-1]['mean_pred']} -> {c['bins'][-1]['mean_actual']}"})
    blocks.append({"title": "B6.4 Calibration (held-out season): slope below 1 means the spread is overstated", "rows": crows,
                   "cols": [["model", "Model"], ["slope", "Slope", 3], ["intercept", "Intercept", 2], ["r", "r", 3], ["n", "n", 0], ["top", "Top decile pred -> actual"]]})
    iv = out["intervals"]
    md += [f"### 80% prediction intervals for {iv['model']} (residual quantiles fitted on {iv['fit_on'][0]}-{iv['fit_on'][-1]}, coverage tested on {sc['test_season']})", "",
           "| Pos | Projection level | Low | High | Width | n test | Coverage |", "|---|---|---|---|---|---|---|"]
    irows = []
    for pos, rows_ in iv["coverage_on_test"].items():
        for r in rows_:
            md.append(f"| {pos} | {r['level']} | {r['lo']:+.1f} | {r['hi']:+.1f} | {r['width']} | {r['n_test']} | {_fmt(r['coverage'], 3)} |")
            irows.append({"pos": pos, "level": r["level"], "lo": r["lo"], "hi": r["hi"], "n": r["n_test"], "cov": r["coverage"]})
    md.append("")
    blocks.append({"title": f"80% prediction intervals ({iv['model']}): add Low and High to the projection; coverage should be near 0.80", "rows": irows,
                   "cols": [["pos", "Pos"], ["level", "Projection"], ["lo", "Low", 1], ["hi", "High", 1], ["n", "n test", 0], ["cov", "Coverage", 3]]})
    # slot gaps
    sg = out["slot_gaps"]
    md += [f"## B6.6 Where lineup points leak (select block, manager rule: {sg['manager_rule']}; {sg['n_team_weeks']:,} team-weeks)", "",
           f"Total gap to the hindsight-optimal lineup: {sg['total_gap_per_week']} points per team-week.", "", "| Slot | Gap / week | Share |", "|---|---|---|"]
    srows_ = []
    for r in sg["by_slot"]:
        md.append(f"| {r['slot']} | {r['gap_per_week']} | {_fmt((r['share'] or 0) * 100, 1)}% |")
        srows_.append({"slot": r["slot"], "gap": r["gap_per_week"], "share": (r["share"] or 0) * 100})
    md.append("")
    fv = out["slot_gaps_flex_view"]
    md += ["FLEX view (same team-weeks): the five skill starters split into the RB/WR core (best two RB and best two WR actually started) and the FLEX picks (everything else, including any TE).", "",
           "| Slot group | Gap / week | Share |", "|---|---|---|"]
    for r in fv["by_slot"]:
        md.append(f"| {r['slot']} | {r['gap_per_week']} | {_fmt((r['share'] or 0) * 100, 1)}% |")
        srows_.append({"slot": r["slot"] + " (FLEX view)", "gap": r["gap_per_week"], "share": (r["share"] or 0) * 100})
    md.append("")
    blocks.append({"title": f"B6.6 Where the points leak: gap to the optimal lineup by position ({sg['total_gap_per_week']} pts per team-week in total)", "rows": srows_,
                   "cols": [["slot", "Position / slot group"], ["gap", "Gap / week", 2], ["share", "Share %", 1]],
                   "text": "By position: FLEX decisions sit inside RB, WR and TE. FLEX view: the same points split into the RB/WR core and the FLEX picks."})
    # role change
    md += ["## B6.7 Role-change detection (share jump vs points jump; 2015-2024)", "", "| Share stat | Positions | Jump | Share events | Sustained | False positive rate | With points event | Mean lead (weeks) | Share first | Same week |", "|---|---|---|---|---|---|---|---|---|---|"]
    rc_rows = []
    for r in out["role_change"]:
        md.append(f"| {r['share_stat']} | {'/'.join(r['positions'])} | {r['jump']} | {r['n_share_events']} | {r['n_sustained']} | {_fmt(r['false_positive_rate'], 3)} | {r['n_with_points_event']} | {_fmt(r['mean_lead_weeks'])} | {_fmt(r['share_leads_points_pct'], 3)} | {_fmt(r['same_week_pct'], 3)} |")
        rc_rows.append({"stat": r["share_stat"], "pos": "/".join(r["positions"]), "events": r["n_share_events"], "fpr": r["false_positive_rate"], "lead": r["mean_lead_weeks"], "first": r["share_leads_points_pct"]})
    md.append("")
    blocks.append({"title": "B6.7 Role change: does a jump in usage share show up before a jump in points?", "rows": rc_rows,
                   "cols": [["stat", "Share stat"], ["pos", "Pos"], ["events", "Events", 0], ["fpr", "False positive rate", 3], ["lead", "Mean lead (wks)", 2], ["first", "Share leads %", 3]]})
    # tests
    lt, dt = out["leakage_test"], out["determinism_test"]
    md += ["## Tests", "", f"- Leakage test: season {lt['season']}, weeks after {lt['corrupted_after_week']} corrupted; {lt['week_model_pairs_checked']} week x model pairs checked, {len(lt['leaks'])} changed; control week differs: {lt['control_week_differs']}. **{'PASSED' if lt['passed'] else 'FAILED'}**",
           f"- Determinism test: two identical runs on the held-out season produced identical output ({dt['bytes']:,} bytes). **{'PASSED' if dt['passed'] else 'FAILED'}**", ""]
    headline.append(f"Leakage test {'passed' if lt['passed'] else 'FAILED'} ({lt['week_model_pairs_checked']} week x model checks); determinism test {'passed' if dt['passed'] else 'FAILED'}.")
    md += ["## Limitations", ""] + [f"- {x}" for x in out["limitations"]] + [""]
    md += ["## Volume coefficients (fit block)", "", "| Pos | Intercept | targets | carries | red-zone touches | pass attempts |", "|---|---|---|---|---|---|"]
    for pos, c in out["volume_coefs"].items():
        md.append(f"| {pos} | {c['intercept']} | {c['targets']} | {c['carries']} | {c['rz']} | {c['pass_att']} |")
    md.append("")
    vout = out.pop("vacated_full", None)
    if vout:
        from . import histvacated
        md += histvacated.markdown(vout)
        blocks += histvacated.blocks(vout)
        headline += histvacated.headline(vout)
        out["vacated"] = {k: v for k, v in vout.items() if k != "injuries_coverage"}
    out["scope_line"] = scope_line
    out["headline"] = headline
    out["blocks"] = blocks
    store.write_json(os.path.join(d, "hist_backtest.json"), out)
    store.write_text(os.path.join(d, "hist_backtest.md"), "\n".join(md) + "\n")
