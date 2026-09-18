"""Statistics for the historical harness (B6). Stdlib only; every function returns plain dicts
with n attached so the findings doc can report sample sizes next to every number.

  B6.1 split_half        odd-week vs even-week correlation of each stat, Spearman-Brown corrected
  B6.2 persistence       autocorrelation of each stat at lags 1..6 and the best simple/decay window
  B6.3 noise_floor       between- vs within-player variance; minimum MAE for a perfect-mean model
  B6.4 calibration       decile table, slope of actual on predicted, empirical prediction intervals
  B6.5 paired_bootstrap  week-level paired bootstrap of a metric difference
  B6.6 slot_gaps         where lineup points leak, by roster slot
  B6.7 role_change       does a jump in target/carry share lead a jump in points?
"""
import math
import random
import statistics
from collections import defaultdict

STATS = {
    "ppg": lambda g: g["pts"],
    "targets_pg": lambda g: g["targets"],
    "target_share": lambda g: g["tgt_share_calc"],
    "carries_pg": lambda g: g["carries"],
    "carry_share": lambda g: g["car_share"],
    "rz_touches_pg": lambda g: g["rz"],
    "yards_per_touch": lambda g: (g["yards"] / g["touches"]) if g["touches"] else None,
    "td_rate": lambda g: (g["tds"] / g["touches"]) if g["touches"] else None,
    "air_yards_share": lambda g: g["ay_share"],
    "pass_att_pg": lambda g: g["pass_att"],
}
STAT_POS = {   # which positions a stat is meaningful for
    "ppg": ("QB", "RB", "WR", "TE"), "targets_pg": ("RB", "WR", "TE"), "target_share": ("RB", "WR", "TE"),
    "carries_pg": ("RB", "QB"), "carry_share": ("RB",), "rz_touches_pg": ("RB", "WR", "TE"),
    "yards_per_touch": ("RB", "WR", "TE"), "td_rate": ("RB", "WR", "TE"), "air_yards_share": ("WR", "TE"),
    "pass_att_pg": ("QB",),
}


def pearson(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else None


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


def spearman(x, y):
    if len(x) < 3:
        return None
    return pearson(_rank(x), _rank(y))


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def games_by_player(season, min_games):
    g = defaultdict(list)
    for p in season["players"]:
        g[p["pid"]].append(p)
    return {pid: sorted(v, key=lambda r: r["week"]) for pid, v in g.items() if len(v) >= min_games}


# ------------------------------------------------------------------ B6.1
def split_half(seasons, min_games=10):
    """Per stat and position: pooled odd/even correlation across seasons (player-seasons as units)."""
    out = []
    for stat, fn in STATS.items():
        for pos in STAT_POS[stat]:
            xs, ys = [], []
            per_season = []
            for s in seasons:
                sx, sy = [], []
                for pid, games in games_by_player(s, min_games).items():
                    if games[0]["pos"] != pos:
                        continue
                    odd = [fn(g) for g in games if g["week"] % 2 == 1]
                    even = [fn(g) for g in games if g["week"] % 2 == 0]
                    odd = [v for v in odd if v is not None]
                    even = [v for v in even if v is not None]
                    if len(odd) >= 3 and len(even) >= 3:
                        sx.append(sum(odd) / len(odd))
                        sy.append(sum(even) / len(even))
                r = pearson(sx, sy)
                if r is not None:
                    per_season.append({"season": s["season"], "r": round(r, 3), "n": len(sx)})
                xs += sx
                ys += sy
            r = pearson(xs, ys)
            sb = (2 * r / (1 + r)) if r is not None and r > -1 else None
            out.append({"stat": stat, "pos": pos, "n_player_seasons": len(xs), "r_half": round(r, 3) if r is not None else None,
                        "r_spearman_brown": round(sb, 3) if sb is not None else None,
                        "seasons": len(per_season), "min_games": min_games,
                        "r_by_season_min": min((x["r"] for x in per_season), default=None),
                        "r_by_season_max": max((x["r"] for x in per_season), default=None)})
    out.sort(key=lambda r: -(r["r_spearman_brown"] or -9))
    return out


# ------------------------------------------------------------------ B6.2
def persistence(seasons, max_lag=6, min_games=8, windows=(1, 2, 3, 4, 5, 6, 8), decays=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6)):
    """Autocorrelation at lags 1..max_lag by stat and position (within player-season, game order),
    and the simple-window / decay that best predicts the next game (MAE), all positions pooled."""
    out = []
    for stat, fn in STATS.items():
        for pos in STAT_POS[stat]:
            lag_x = {L: ([], []) for L in range(1, max_lag + 1)}
            win_err = {w: [] for w in windows}
            dec_err = {a: [] for a in decays}
            for s in seasons:
                for pid, games in games_by_player(s, min_games).items():
                    if games[0]["pos"] != pos:
                        continue
                    vals = [fn(g) for g in games]
                    vals = [v if v is not None else 0.0 for v in vals]
                    for L in lag_x:
                        for i in range(L, len(vals)):
                            lag_x[L][0].append(vals[i - L])
                            lag_x[L][1].append(vals[i])
                    for i in range(1, len(vals)):
                        past = vals[:i]
                        for w in windows:
                            win_err[w].append(abs(sum(past[-w:]) / len(past[-w:]) - vals[i]))
                        for a in decays:
                            wt = [(1 - a) ** j for j in range(len(past))]
                            e = sum(x * y for x, y in zip(reversed(past), wt)) / sum(wt)
                            dec_err[a].append(abs(e - vals[i]))
            lags = {L: (round(pearson(x, y), 3) if pearson(x, y) is not None else None) for L, (x, y) in lag_x.items()}
            n_lag1 = len(lag_x[1][0])
            wm = {w: round(mean(e), 4) for w, e in win_err.items() if e}
            dm = {a: round(mean(e), 4) for a, e in dec_err.items() if e}
            out.append({"stat": stat, "pos": pos, "n_pairs_lag1": n_lag1, "autocorr": lags,
                        "best_window": min(wm, key=wm.get) if wm else None, "window_mae": wm,
                        "best_decay": min(dm, key=dm.get) if dm else None, "decay_mae": dm})
    return out


# ------------------------------------------------------------------ B6.3
def noise_floor(seasons, min_games=8):
    """Variance decomposition of weekly points by position and the MAE of a perfect-mean model."""
    out = {}
    for pos in ("QB", "RB", "WR", "TE", "DEF"):
        within_sq, within_abs, means, all_pts, n_players = [], [], [], [], 0
        for s in seasons:
            if pos == "DEF":
                gb = defaultdict(list)
                for d in s["defense"]:
                    gb[d["team"]].append(d["pts"])
                groups = [v for v in gb.values() if len(v) >= min_games]
            else:
                groups = [[g["pts"] for g in games] for games in games_by_player(s, min_games).values() if games[0]["pos"] == pos]
            for pts in groups:
                m = sum(pts) / len(pts)
                means.append(m)
                n_players += 1
                for x in pts:
                    within_sq.append((x - m) ** 2)
                    within_abs.append(abs(x - m))
                    all_pts.append(x)
        if not all_pts:
            continue
        total_var = statistics.pvariance(all_pts)
        between_var = statistics.pvariance(means) if len(means) > 1 else 0.0
        within_var = mean(within_sq)
        out[pos] = {"n_player_seasons": n_players, "n_player_weeks": len(all_pts), "min_games": min_games,
                    "total_var": round(total_var, 2), "between_player_var": round(between_var, 2), "within_player_var": round(within_var, 2),
                    "share_predictable": round(between_var / total_var, 3) if total_var else None,
                    "floor_mae_known_mean": round(mean(within_abs), 3), "floor_rmse_known_mean": round(math.sqrt(within_var), 3)}
    return out


# ------------------------------------------------------------------ B6.4
def calibration(pairs, n_bins=10):
    """pairs: list of (pred, actual). Decile table + OLS slope of actual on predicted."""
    if len(pairs) < 20:
        return None
    ps = sorted(pairs)
    n = len(ps)
    bins = []
    for b in range(n_bins):
        chunk = ps[b * n // n_bins:(b + 1) * n // n_bins]
        if chunk:
            bins.append({"decile": b + 1, "n": len(chunk), "mean_pred": round(mean([p for p, _ in chunk]), 2),
                         "mean_actual": round(mean([a for _, a in chunk]), 2)})
    x = [p for p, _ in pairs]
    y = [a for _, a in pairs]
    mx, my = mean(x), mean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx if sxx else None
    r = pearson(x, y)
    return {"n": n, "bins": bins, "slope_actual_on_pred": round(slope, 3) if slope is not None else None,
            "intercept": round(my - slope * mx, 2) if slope is not None else None, "r": round(r, 3) if r is not None else None}


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def level_bin(pred):
    if pred < 5:
        return "under 5"
    if pred < 10:
        return "5 to 10"
    if pred < 15:
        return "10 to 15"
    if pred < 20:
        return "15 to 20"
    return "20 plus"


def fit_intervals(pairs_by_pos, level=0.8):
    """Empirical residual quantiles by position and projection level. Returns {pos: {bin: (lo, hi, n)}}."""
    lo_q, hi_q = (1 - level) / 2, 1 - (1 - level) / 2
    out = {}
    for pos, pairs in pairs_by_pos.items():
        byb = defaultdict(list)
        for p, a in pairs:
            byb[level_bin(p)].append(a - p)
        out[pos] = {}
        for b, res in byb.items():
            res.sort()
            if len(res) >= 30:
                out[pos][b] = {"lo": round(_quantile(res, lo_q), 2), "hi": round(_quantile(res, hi_q), 2), "n_fit": len(res)}
    return out


def test_intervals(intervals, pairs_by_pos):
    out = {}
    for pos, pairs in pairs_by_pos.items():
        rows = []
        for b, iv in (intervals.get(pos) or {}).items():
            inside, n = 0, 0
            for p, a in pairs:
                if level_bin(p) == b:
                    n += 1
                    inside += 1 if iv["lo"] <= a - p <= iv["hi"] else 0
            if n:
                rows.append({"level": b, "lo": iv["lo"], "hi": iv["hi"], "width": round(iv["hi"] - iv["lo"], 1),
                             "n_test": n, "coverage": round(inside / n, 3)})
        out[pos] = rows
    return out


# ------------------------------------------------------------------ B6.5
def paired_bootstrap(diffs_by_week, n_boot=4000, seed=20260918):
    """diffs_by_week: {week: mean difference (model minus baseline) over that week's units}.
    Resamples weeks with replacement. Returns mean diff and 95% interval."""
    weeks = list(diffs_by_week.values())
    if len(weeks) < 3:
        return {"n_weeks": len(weeks), "mean": mean(weeks), "lo": None, "hi": None, "crosses_zero": None}
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        s = [weeks[rng.randrange(len(weeks))] for _ in weeks]
        boots.append(sum(s) / len(s))
    boots.sort()
    lo, hi = _quantile(boots, 0.025), _quantile(boots, 0.975)
    return {"n_weeks": len(weeks), "mean": round(mean(weeks), 3), "lo": round(lo, 3), "hi": round(hi, 3),
            "crosses_zero": lo <= 0 <= hi, "n_boot": n_boot}


# ------------------------------------------------------------------ B6.6
def slot_gaps(lineup_rows, slots):
    """lineup_rows: list of {"chosen": {slot: pts}, "optimal": {slot: pts}} per team-week (points at each slot,
    positions ordered best-first within a slot type). Returns per-slot mean gap and share of total gap."""
    gap = defaultdict(float)
    n = 0
    for r in lineup_rows:
        n += 1
        for s in slots:
            gap[s] += (r["optimal"].get(s) or 0) - (r["chosen"].get(s) or 0)
    total = sum(gap.values())
    return {"n_team_weeks": n, "total_gap_per_week": round(total / n, 2) if n else None,
            "by_slot": [{"slot": s, "gap_per_week": round(gap[s] / n, 2) if n else None,
                         "share": round(gap[s] / total, 3) if total else None} for s in slots]}


# ------------------------------------------------------------------ B6.7
def role_change(seasons, share_key, pos_filter, jump=0.10, pts_jump=5.0, pre=4, post=3, min_games=10):
    """A share event at game i: mean share of games [i, i+1] exceeds mean of the previous `pre` games by `jump`.
    'Real' if the following `post` games' mean share also exceeds the pre mean by `jump` (sustained).
    Points event: the same rule on points with `pts_jump`. Lead time = points-event game minus share-event game
    for players with both a real share event and a points event within 6 games of it."""
    events, real, leads, pts_only = 0, 0, [], 0
    for s in seasons:
        for pid, games in games_by_player(s, min_games).items():
            if games[0]["pos"] not in pos_filter:
                continue
            sh = [g[share_key] for g in games]
            pt = [g["pts"] for g in games]
            i = pre
            while i + post + 1 < len(games):
                base = sum(sh[i - pre:i]) / pre
                cur = (sh[i] + sh[i + 1]) / 2
                if cur - base >= jump:
                    events += 1
                    after = sum(sh[i + 2:i + 2 + post]) / post
                    is_real = after - base >= jump
                    real += 1 if is_real else 0
                    if is_real:
                        pbase = sum(pt[i - pre:i]) / pre
                        j = i
                        found = None
                        while j < min(len(games) - 1, i + 6):
                            if (pt[j] + pt[j + 1]) / 2 - pbase >= pts_jump:
                                found = j
                                break
                            j += 1
                        if found is not None:
                            leads.append(found - i)
                        else:
                            pts_only += 1
                    i += pre        # skip ahead so one shift is not counted repeatedly
                else:
                    i += 1
    return {"share_stat": share_key, "positions": list(pos_filter), "jump": jump, "points_jump": pts_jump,
            "n_share_events": events, "n_sustained": real, "false_positive_rate": round(1 - real / events, 3) if events else None,
            "n_with_points_event": len(leads), "n_sustained_without_points_event": pts_only,
            "mean_lead_weeks": round(mean(leads), 2) if leads else None,
            "share_leads_points_pct": round(sum(1 for L in leads if L > 0) / len(leads), 3) if leads else None,
            "same_week_pct": round(sum(1 for L in leads if L == 0) / len(leads), 3) if leads else None}
