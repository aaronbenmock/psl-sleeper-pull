"""Point-in-time prediction models for the historical replay (stdlib only).

Every prediction for week N of a season uses only games from weeks earlier than N in that season
plus completed prior seasons (the prior-season points per game, and coefficients fitted on the
fit block of seasons). Nothing from week N or later is read: the SeasonIndex exposes a player's
games as a list sorted by week and every feature function slices strictly below N. The leakage
test in histbacktest corrupts weeks >= N and asserts byte-identical predictions for weeks < N.

Models (name -> config):
  naive              season average to date (the engine's current baseline half); prior when no games
  lastN:N            mean of the last N games
  ewma:a             recency-weighted mean, weight (1-a)^lag, a fitted on the fit block (B6.2)
  kblend:k           (n x avg + k x prior) / (n + k), the engine's baseline half, k swept
  ewk:a:k            recency-weighted mean shrunk to the prior with strength k
  vol:lam:k          volume-share model (proposal item 5): each past game's points are replaced by
                     lam x volume-implied points + (1 - lam) x actual points, where volume-implied
                     points = per-position least squares on targets, carries, red-zone touches and
                     pass attempts fitted on the fit block; the series is then shrunk to the prior (k)
  +opp:g:m           opponent adjustment (item 4): multiply by (points allowed by the opponent to
                     the position, recency-weighted, shrunk with m games of league average)
                     / league average, raised to g
prior = the player's previous-season points per game (min 4 games); otherwise a position default
equal to the 25th percentile of previous-season ppg among players with 6+ games (replacement level).
"""
from collections import defaultdict

FEATS = ["targets", "carries", "rz", "pass_att"]
OFF_POS = ("QB", "RB", "WR", "TE")


# ------------------------------------------------------------------ small linear algebra
def solve(A, b):
    """Gaussian elimination with partial pivoting; A is n x n (list of lists), b length n."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12:
            M[c][c] += 1e-6          # ridge nudge for a degenerate column
        M[c], M[p] = M[p], M[c]
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                if f:
                    for k in range(c, n + 1):
                        M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def least_squares(rows, feats, target="pts", ridge=1.0):
    """Fit target ~ 1 + feats by ridge-regularised normal equations. Returns coefficient list."""
    k = len(feats) + 1
    A = [[0.0] * k for _ in range(k)]
    b = [0.0] * k
    for r in rows:
        x = [1.0] + [float(r.get(f) or 0.0) for f in feats]
        y = float(r[target])
        for i in range(k):
            b[i] += x[i] * y
            for j in range(k):
                A[i][j] += x[i] * x[j]
    for i in range(1, k):
        A[i][i] += ridge
    return solve(A, b)


def fit_volume_coefs(seasons):
    """Per-position coefficients of points on volume, fitted on the given seasons (the fit block)."""
    by_pos = defaultdict(list)
    for s in seasons:
        for p in s["players"]:
            by_pos[p["pos"]].append(p)
    return {pos: least_squares(rows, FEATS) for pos, rows in by_pos.items()}


def implied(coefs, p):
    c = coefs
    return c[0] + sum(c[i + 1] * float(p.get(f) or 0.0) for i, f in enumerate(FEATS))


# ------------------------------------------------------------------ priors
def prior_table(prev_season, min_games=4, default_pct=0.25, min_games_default=6):
    """{pid: prior ppg} and {pos: default prior} from a completed previous season (None -> empties)."""
    if not prev_season:
        return {}, {pos: 5.0 for pos in OFF_POS}, {}, 5.0
    games = defaultdict(list)
    pos_of = {}
    for p in prev_season["players"]:
        games[p["pid"]].append(p["pts"])
        pos_of[p["pid"]] = p["pos"]
    prior = {pid: sum(g) / len(g) for pid, g in games.items() if len(g) >= min_games}
    by_pos = defaultdict(list)
    for pid, g in games.items():
        if len(g) >= min_games_default:
            by_pos[pos_of[pid]].append(sum(g) / len(g))
    defaults = {}
    for pos in OFF_POS:
        v = sorted(by_pos.get(pos) or [5.0])
        defaults[pos] = v[int(default_pct * (len(v) - 1))]
    dgames = defaultdict(list)
    for d in prev_season["defense"]:
        dgames[d["team"]].append(d["pts"])
    dprior = {t: sum(g) / len(g) for t, g in dgames.items() if len(g) >= min_games}
    dvals = sorted(dprior.values()) or [5.0]
    ddefault = dvals[int(default_pct * (len(dvals) - 1))]
    return prior, defaults, dprior, ddefault


# ------------------------------------------------------------------ index
class SeasonIndex:
    def __init__(self, season, prev_season, coefs):
        self.season = season["season"]
        self.weeks = season["weeks"]
        self.games = defaultdict(list)          # pid -> [rec] sorted by week
        self.by_week = defaultdict(list)        # week -> [rec]
        self.pos_of, self.name_of = {}, {}
        for p in sorted(season["players"], key=lambda r: r["week"]):
            self.games[p["pid"]].append(p)
            self.by_week[p["week"]].append(p)
            self.pos_of[p["pid"]] = p["pos"]
            self.name_of[p["pid"]] = p["name"]
        self.dgames = defaultdict(list)
        self.dby_week = defaultdict(list)
        for d in sorted(season["defense"], key=lambda r: r["week"]):
            self.dgames[d["team"]].append(d)
            self.dby_week[d["week"]].append(d)
        self.prior, self.pos_default, self.dprior, self.ddefault = prior_table(prev_season)
        self.coefs = coefs
        # points allowed to each position by each defense, per week (from the week's rows only)
        self.allowed = defaultdict(lambda: defaultdict(dict))    # pos -> team -> week -> pts allowed
        for wk, rows in self.by_week.items():
            acc = defaultdict(float)
            for p in rows:
                if p["opp"]:
                    acc[(p["pos"], p["opp"])] += p["pts"]
            for (pos, team), v in acc.items():
                self.allowed[pos][team][wk] = v
        # points scored by defenses against each offense per week (for DEF opponent adjustment)
        self.allowed_by_off = defaultdict(dict)                  # offense team -> week -> DEF pts scored against it
        for wk, rows in self.dby_week.items():
            for d in rows:
                if d["opp"]:
                    self.allowed_by_off[d["opp"]][wk] = d["pts"]
        self._cache = {}

    def prior_of(self, pid):
        v = self.prior.get(pid)
        return v if v is not None else self.pos_default.get(self.pos_of.get(pid), 5.0)

    def dprior_of(self, team):
        v = self.dprior.get(team)
        return v if v is not None else self.ddefault

    def history(self, pid, week):
        """Games strictly before `week` (the only accessor models may use)."""
        return [g for g in self.games[pid] if g["week"] < week]

    def dhistory(self, team, week):
        return [g for g in self.dgames[team] if g["week"] < week]

    # league-average points allowed to a position per team-game, from weeks < week (cached)
    def league_allowed(self, pos, week):
        key = ("la", pos, week)
        if key in self._cache:
            return self._cache[key]
        tot, n = 0.0, 0
        for team, wks in self.allowed[pos].items():
            for wk, v in wks.items():
                if wk < week:
                    tot += v
                    n += 1
        self._cache[key] = (tot / n) if n else None
        return self._cache[key]

    def allowed_ewma(self, pos, team, week, a):
        key = ("ae", pos, team, week, a)
        if key in self._cache:
            return self._cache[key]
        pts = sorted((wk, v) for wk, v in self.allowed[pos].get(team, {}).items() if wk < week)
        if not pts:
            self._cache[key] = (None, 0)
            return self._cache[key]
        w, s = 0.0, 0.0
        for i, (wk, v) in enumerate(reversed(pts)):
            wt = (1 - a) ** i
            w += wt
            s += wt * v
        self._cache[key] = (s / w, len(pts))
        return self._cache[key]


# ------------------------------------------------------------------ series helpers
def ewma(vals, a):
    if not vals:
        return None
    w, s = 0.0, 0.0
    for i, v in enumerate(reversed(vals)):
        wt = (1 - a) ** i
        w += wt
        s += wt * v
    return s / w


def mean(vals):
    return sum(vals) / len(vals) if vals else None


# ------------------------------------------------------------------ prediction
def parse_model(name):
    """'kblend:4+opp:1.0:4' -> (base, params, opp params or None)."""
    parts = name.split("+")
    base = parts[0].split(":")
    opp = None
    for extra in parts[1:]:
        e = extra.split(":")
        if e[0] == "opp":
            opp = {"g": float(e[1]), "m": float(e[2]), "a": float(e[3]) if len(e) > 3 else 0.2}
    return base[0], base[1:], opp


def base_prediction(idx, pid, week, kind, params):
    hist = idx.history(pid, week)
    pts = [g["pts"] for g in hist]
    prior = idx.prior_of(pid)
    n = len(pts)
    if kind == "naive":
        return mean(pts) if n else prior
    if kind == "lastN":
        N = int(params[0])
        return mean(pts[-N:]) if n else prior
    if kind == "ewma":
        return ewma(pts, float(params[0])) if n else prior
    if kind == "kblend":
        k = float(params[0])
        return (n * mean(pts) + k * prior) / (n + k) if n else prior
    if kind == "ewk":
        a, k = float(params[0]), float(params[1])
        if not n:
            return prior
        e = ewma(pts, a)
        return (n * e + k * prior) / (n + k)
    if kind == "vol":
        lam, k = float(params[0]), float(params[1])
        a = float(params[2]) if len(params) > 2 else None
        if not n:
            return prior
        coefs = idx.coefs.get(idx.pos_of.get(pid))
        series = [lam * implied(coefs, g) + (1 - lam) * g["pts"] if coefs else g["pts"] for g in hist]
        m = ewma(series, a) if a else mean(series)
        return (n * m + k * prior) / (n + k)
    raise ValueError(kind)


def opp_multiplier(idx, pos, opp, week, g, m, a):
    if not opp:
        return 1.0
    la = idx.league_allowed(pos, week)
    if not la:
        return 1.0
    mu, n = idx.allowed_ewma(pos, opp, week, a)
    if mu is None:
        return 1.0
    shr = (n * mu + m * la) / (n + m)
    return (shr / la) ** g


def predict_week(idx, week, model):
    """{pid: prediction} for every offensive player with a stat row in `week`."""
    kind, params, opp = parse_model(model)
    out = {}
    for p in idx.by_week.get(week, []):
        pred = base_prediction(idx, p["pid"], week, kind, params)
        if opp:
            pred *= opp_multiplier(idx, p["pos"], p["opp"], week, opp["g"], opp["m"], opp["a"])
        out[p["pid"]] = round(pred, 4)
    return out


def def_base_prediction(idx, team, week, kind, params):
    hist = idx.dhistory(team, week)
    pts = [g["pts"] for g in hist]
    prior = idx.dprior_of(team)
    n = len(pts)
    if kind in ("naive",):
        return mean(pts) if n else prior
    if kind == "lastN":
        return mean(pts[-int(params[0]):]) if n else prior
    if kind == "ewma":
        return ewma(pts, float(params[0])) if n else prior
    if kind in ("kblend", "vol"):
        k = float(params[0]) if kind == "kblend" else float(params[1])
        return (n * mean(pts) + k * prior) / (n + k) if n else prior
    if kind == "ewk":
        a, k = float(params[0]), float(params[1])
        return (n * ewma(pts, a) + k * prior) / (n + k) if n else prior
    raise ValueError(kind)


def predict_def_week(idx, week, model):
    kind, params, opp = parse_model(model)
    out = {}
    if opp:
        # league average DEF points per team-game before this week
        vals = [v for wks in idx.allowed_by_off.values() for wk, v in wks.items() if wk < week]
        la = mean(vals)
    for d in idx.dby_week.get(week, []):
        pred = def_base_prediction(idx, d["team"], week, kind, params)
        if opp and la and d["opp"]:
            pts = sorted((wk, v) for wk, v in idx.allowed_by_off.get(d["opp"], {}).items() if wk < week)
            if pts:
                mu = ewma([v for _, v in pts], opp["a"])
                shr = (len(pts) * mu + opp["m"] * la) / (len(pts) + opp["m"])
                # DEF points are near zero on average, so use an additive shift rather than a ratio
                pred += opp["g"] * (shr - la)
        out[d["team"]] = round(pred, 4)
    return out
