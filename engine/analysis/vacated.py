"""Vacated target share: how much of an absent teammate's usage this player is likely to absorb.

DISPLAY ONLY. Nothing in this module may reach `expected` in recommend.py. The reason is written
down in Fantasy-Football/Backtest-Findings_v1.0_2026-09-18.md: on ten seasons of held-out data the
opponent and role adjustments were not distinguishable from zero outside DEF, so no new term enters
the projection until it has been measured on this league's own results. tests/test_vacated.py
asserts the separation.

The three steps, in the order the spec states them:

1. Vacated share. For a player at position P on team T in week W, sum the prior usage share of
   every teammate at the same position who is absent that week (Out, Doubtful, IR, PUP, Suspended,
   or an inactive Sleeper roster status). Prior share = his recency-weighted season-to-date share
   of the team's targets (and of the team's carries, for RB), shrunk to his previous-season share
   with k = 4, the same shrinkage the engine's baseline already uses.
2. Expected absorption. Two estimators:
     proportional  the vacated share is split among the remaining teammates at that position in
                   proportion to their own prior shares.
     historical    for each absent teammate, the share this player actually took in past games
                   where that teammate was absent, minus his share in games where the teammate
                   played. Needs at least MIN_HIST_GAMES games on each side; falls back to the
                   proportional number for that teammate otherwise.
   Whichever the backtest prefers is the one the live column uses (see ESTIMATOR below).
3. Points equivalent. Absorbed share x the team's recency-weighted opportunities per game x the
   player's own shrunk points per opportunity, so the column reads in points like everything else.

Position groups are narrow on purpose: a WR's vacated share counts absent WRs only, and the
proportional estimator then redistributes it among the remaining WRs. Targets vacated by a TE do
flow to WRs in reality; counting them would need a cross-position absorption matrix the backtest
has no power to fit, so the narrow reading is the honest one and is stated here rather than buried.
"""
from collections import defaultdict

PRIOR_GAMES = 4          # same shrinkage strength as recommend.PRIOR_GAMES
DECAY = 0.1              # recency weight (1 - DECAY) ** lag; the decay the fit block chose in hist_backtest
PPO_PRIOR_OPPS = 12      # pseudo-opportunities of prior weight on points per opportunity
MIN_HIST_GAMES = 3       # the historical estimator needs this many games on each side
CLOSE_GAP = 1.5          # the engine's close-call width, kept here so the backtest uses one constant

POS_OK = ("WR", "RB", "TE")
GROUP = {"WR": ("WR",), "RB": ("RB",), "TE": ("TE",)}
KINDS = {"WR": ("tgt",), "TE": ("tgt",), "RB": ("car", "tgt")}

# Statuses that mean "not playing": Sleeper's injury_status, plus its roster status field.
ABSENT_STATUS = {"Out", "Doubtful", "IR", "PUP", "Sus", "NA", "DNR", "COV"}
ABSENT_ROSTER_STATUS = {"Inactive", "Injured Reserve", "Non Football Injury", "Practice Squad",
                        "Physically Unable to Perform", "Suspended", "Reserve/COVID-19"}

ESTIMATOR = "historical"     # what the 2015-2024 select block preferred; see docs/METHOD.md section 10


def is_absent(injury_status=None, roster_status=None):
    return bool((injury_status in ABSENT_STATUS) or (roster_status in ABSENT_ROSTER_STATUS))


# ---------------------------------------------------------------- small helpers
def ewma(vals, a=DECAY):
    """Recency-weighted mean; vals oldest first."""
    if not vals:
        return None
    w = s = 0.0
    for i, v in enumerate(reversed(vals)):
        wt = (1 - a) ** i
        w += wt
        s += wt * v
    return s / w


def shrink(n, obs, prior, k=PRIOR_GAMES):
    """(n x obs + k x prior) / (n + k), the engine's baseline shrinkage."""
    if obs is None:
        return prior
    if prior is None:
        return obs
    return (n * obs + k * prior) / (n + k)


def _r(v, n=3):
    return None if v is None else round(v, n)


# ---------------------------------------------------------------- usage book
class Usage:
    """Point-in-time index of weekly usage. Every accessor slices strictly before the asked week,
    which is what makes the historical replay honest.

    rows        {"pid", "name", "pos", "team", "season", "week", "tgt", "car", "rec_pts", "rush_pts"}
    team_tot    {(season, week, team): {"tgt": x, "car": y}}
    absent      {(season, week, team): set(pid)}  who did not play, decided before kickoff
    prior       {pid: {"team", "pos", "tgt_share", "car_share", "ppt", "ppc", "g"}} previous season
    prior_team  {team: {"tgt", "car"}} previous-season opportunities per game
    prior_pos   {pos: {"ppt", "ppc"}} previous-season league means, the fallback prior
    """

    def __init__(self, rows, team_tot, absent=None, prior=None, prior_team=None, prior_pos=None, season=None):
        self.season = season
        self.rows = rows
        self.team_tot = team_tot
        self.absent = absent or {}
        self.prior = prior or {}
        self.prior_team = prior_team or {}
        self.prior_pos = prior_pos or {}
        self.games = defaultdict(list)
        self.by_team = defaultdict(set)
        self.pos_of, self.name_of, self.team_of = {}, {}, {}
        for r in sorted(rows, key=lambda r: (r.get("season") or 0, r["week"])):
            self.games[r["pid"]].append(r)
            self.by_team[(r.get("season"), r["team"], r["pos"])].add(r["pid"])
            self.pos_of[r["pid"]] = r["pos"]
            self.name_of[r["pid"]] = r.get("name") or r["pid"]
            self.team_of[r["pid"]] = r["team"]
        for pid, pr in (prior or {}).items():
            self.pos_of.setdefault(pid, pr.get("pos"))
            self.name_of.setdefault(pid, pr.get("name") or pid)
        self.team_games = defaultdict(list)
        for (s, w, t), v in sorted(team_tot.items()):
            self.team_games[(s, t)].append((w, v))
        self._cache = {}

    # ---- slicing
    def history(self, pid, season, week):
        return [g for g in self.games.get(pid, []) if g.get("season") == season and g["week"] < week]

    def all_history(self, pid, season, week):
        """Every game of this player strictly before (season, week), prior seasons included."""
        return [g for g in self.games.get(pid, []) if (g.get("season"), g["week"]) < (season, week)]

    def teammates(self, team, pos, season, week):
        """Everyone at `pos` with usage on `team` before `week` this season, plus anyone the previous
        season listed there (a starter who has been out since week 1 still vacates his prior share)."""
        out = {pid for pid in self.by_team.get((season, team, pos), set()) if self.history(pid, season, week)}
        for pid, pr in self.prior.items():
            if pr.get("team") == team and pr.get("pos") == pos:
                out.add(pid)
        return out

    # ---- shares
    def shares(self, pid, season, week):
        key = ("sh", pid, season, week)
        if key in self._cache:
            return self._cache[key]
        hist = self.history(pid, season, week)
        pr = self.prior.get(pid) or {}
        out = {"n": len(hist)}
        for col in ("tgt", "car"):
            per_game = []
            for g in hist:
                tt = self.team_tot.get((g.get("season"), g["week"], g["team"])) or {}
                tot = tt.get(col) or 0.0
                per_game.append((g.get(col) or 0.0) / tot if tot else 0.0)
            v = shrink(len(hist), ewma(per_game), pr.get(col + "_share"))
            out[col] = 0.0 if v is None else v
        self._cache[key] = out
        return out

    def ppo(self, pid, season, week):
        """Shrunk points per target and points per carry."""
        key = ("ppo", pid, season, week)
        if key in self._cache:
            return self._cache[key]
        hist = self.history(pid, season, week)
        pr = self.prior.get(pid) or {}
        pos_pr = self.prior_pos.get(self.pos_of.get(pid)) or {}
        out = {}
        for kind, opp_col, pts_col in (("ppt", "tgt", "rec_pts"), ("ppc", "car", "rush_pts")):
            opps = sum(g.get(opp_col) or 0.0 for g in hist)
            pts = sum(g.get(pts_col) or 0.0 for g in hist)
            prior = pr.get(kind)
            if prior is None:
                prior = pos_pr.get(kind) or 0.0
            out[kind] = (pts + PPO_PRIOR_OPPS * prior) / (opps + PPO_PRIOR_OPPS)
        self._cache[key] = out
        return out

    def team_per_game(self, team, season, week):
        key = ("tpg", team, season, week)
        if key in self._cache:
            return self._cache[key]
        gs = [v for w, v in self.team_games.get((season, team), []) if w < week]
        pr = self.prior_team.get(team) or {}
        out = {}
        for col in ("tgt", "car"):
            v = shrink(len(gs), ewma([g.get(col) or 0.0 for g in gs]), pr.get(col))
            out[col] = 0.0 if v is None else v
        self._cache[key] = out
        return out

    def was_absent(self, pid, season, week, team):
        return pid in (self.absent.get((season, week, team)) or set())


# ---------------------------------------------------------------- the signal
def _hist_delta(u, pid, other, season, week, kind):
    """Share this player took in past games where `other` was absent, minus games where he played.
    Returns (delta, n) with n = the smaller of the two game counts; prior seasons are included."""
    out_vals, in_vals = [], []
    for g in u.all_history(pid, season, week):
        tt = u.team_tot.get((g.get("season"), g["week"], g["team"])) or {}
        tot = tt.get(kind) or 0.0
        if not tot:
            continue
        share = (g.get(kind) or 0.0) / tot
        if u.was_absent(other, g.get("season"), g["week"], g["team"]):
            out_vals.append(share)
        else:
            in_vals.append(share)
    n = min(len(out_vals), len(in_vals))
    if n < MIN_HIST_GAMES:
        return None, n
    return (sum(out_vals) / len(out_vals)) - (sum(in_vals) / len(in_vals)), n


def signal(u, pid, team, pos, season, week, absent_pids, estimator=None, names=None):
    """The whole column for one player. Returns a dict whose `points` field is what is displayed."""
    estimator = estimator or ESTIMATOR
    if pos not in POS_OK:
        return None
    group = set()
    for p in GROUP.get(pos, (pos,)):
        group |= u.teammates(team, p, season, week)
    out_ids = sorted(q for q in group if q in absent_pids and q != pid)
    kinds = KINDS.get(pos, ("tgt",))
    mine = u.shares(pid, season, week)
    present = [q for q in group if q not in absent_pids and q != pid]
    vac = {k: 0.0 for k in kinds}
    got = {k: 0.0 for k in kinds}
    used_hist, n_hist_min = 0, None
    detail = []
    for other in out_ids:
        osh = u.shares(other, season, week)
        d = {"player_id": other, "name": (names or u.name_of).get(other, other)}
        for k in kinds:
            v = osh.get(k) or 0.0
            vac[k] += v
            if v <= 0:
                d[k] = 0.0
                continue
            take = None
            if estimator == "historical":
                delta, n = _hist_delta(u, pid, other, season, week, k)
                if delta is not None:
                    take = max(0.0, min(v, delta))
                    used_hist += 1
                    n_hist_min = n if n_hist_min is None else min(n_hist_min, n)
            if take is None:
                pool = sum((u.shares(q, season, week).get(k) or 0.0) for q in present) + (mine.get(k) or 0.0)
                take = v * ((mine.get(k) or 0.0) / pool) if pool > 0 else v / (len(present) + 1)
            got[k] += take
            d[k] = round(take, 4)
        detail.append(d)
    tpg = u.team_per_game(team, season, week)
    ppo = u.ppo(pid, season, week)
    points = (got.get("tgt", 0.0) * (tpg["tgt"] or 0.0) * ppo["ppt"]
              + got.get("car", 0.0) * (tpg["car"] or 0.0) * ppo["ppc"])
    return {"player_id": pid, "pos": pos, "team": team, "estimator": estimator,
            "n_out": len(out_ids), "out": detail,
            "vacated_tgt": _r(vac.get("tgt")), "vacated_car": _r(vac.get("car")),
            "absorbed_tgt": _r(got.get("tgt")), "absorbed_car": _r(got.get("car")),
            "own_tgt_share": _r(mine.get("tgt")), "own_car_share": _r(mine.get("car")),
            "ppt": round(ppo["ppt"], 3), "ppc": round(ppo["ppc"], 3),
            "team_tgt_pg": round(tpg["tgt"] or 0.0, 2), "team_car_pg": round(tpg["car"] or 0.0, 2),
            "hist_pairs_used": used_hist, "hist_min_games": n_hist_min,
            "points": round(points, 2), "n_games": mine["n"]}


def why(sig):
    """One plain-English sentence for the dashboard."""
    if not sig:
        return ""
    if not sig["n_out"]:
        return "No teammate at his position is ruled out, so nothing is vacated."
    who = ", ".join(d["name"] for d in sig["out"][:3]) + (f" and {sig['n_out'] - 3} more" if sig["n_out"] > 3 else "")
    lost, took = [], []
    if sig.get("vacated_tgt"):
        lost.append(f"{sig['vacated_tgt'] * 100:.0f}% of the targets")
    if sig.get("vacated_car"):
        lost.append(f"{sig['vacated_car'] * 100:.0f}% of the carries")
    if sig.get("absorbed_tgt"):
        took.append(f"{sig['absorbed_tgt'] * 100:.0f}% of targets")
    if sig.get("absorbed_car"):
        took.append(f"{sig['absorbed_car'] * 100:.0f}% of carries")
    how = "historical" if sig["estimator"] == "historical" and sig.get("hist_pairs_used") else "proportional"
    return (f"{who} out, vacating {' and '.join(lost) or 'no measured usage'}. The {how} split gives him "
            f"{' and '.join(took) or 'none of it'}, worth about {sig['points']:.1f} points. "
            f"Display only: it does not change the expected number.")
