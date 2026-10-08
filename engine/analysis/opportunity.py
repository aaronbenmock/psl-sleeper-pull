"""Opportunity and role-change upside for RB and WR: the ceiling column and the speculative-claim flag.

Built on the vacated-share signal (vacated.py), which docs/METHOD.md section 10 keeps out of
`expected`. Nothing here changes `expected`, `ros`, the waiver gain or the original bid either. It
adds two numbers per player and a separate, clearly labelled speculative tier:

  bump_now        points a week he absorbs from teammates at his position who are absent now
  bump_if_lead    the same with the healthy teammate ahead of him (more usage) also absent:
                  "if the player ahead of him misses time"
  ceiling         ros + max(bump_now, bump_if_lead)

Speculative claims whose role is open now (bump_now >= ROLE_OPEN: the player ahead is already out,
Ollie Gordon with Achane on IR) are listed before the contingent ones.

A waiver player is a speculative claim when the ceiling gap is SPEC_GAP points a week or more, or
when the gain at his ceiling would clear SPEC_GAIN while his normal gain does not earn a bid. The
speculative bid is small and capped: min(SPEC_BUDGET_SHARE x budget left, ceiling gain x weeks left x
$0.60 x SPEC_PROB), at least $1. [Guessing] on all four constants, and untested: the ten-season
backtest found the vacated signal null as a start/sit tiebreak, and nobody has measured it as a
waiver signal.
"""
from . import vacated as vc

SPEC_GAP = 4.0
SPEC_GAIN = 3.0
SPEC_BUDGET_SHARE = 0.05
SPEC_PROB = 0.25
HANDCUFF_MIN = 3.0
ROLE_OPEN = 3.0          # bump_now at or above this = the role is open now, listed first
PRIMARY = {"RB": "car", "WR": "tgt"}
POS = ("RB", "WR")


def lead_teammate(u, gid, team, pos, season, week, absent):
    """The healthy teammate at this position with the most usage, if he has more than this player."""
    k = PRIMARY[pos]
    mine = (u.shares(gid, season, week).get(k) or 0.0)
    best = None
    for q in u.teammates(team, pos, season, week):
        if q == gid or q in absent:
            continue
        s = u.shares(q, season, week).get(k) or 0.0
        if s > mine and (best is None or s > best[1]):
            best = (q, s)
    return best[0] if best else None


def ceiling(u, gid, team, pos, season, week, absent):
    """Returns {"bump_now", "bump_if_lead", "lead", "lead_name", "bump", "why_now"} or None."""
    if pos not in POS:
        return None
    now = vc.signal(u, gid, team, pos, season, week, set(absent))
    lead = lead_teammate(u, gid, team, pos, season, week, set(absent))
    if_lead = vc.signal(u, gid, team, pos, season, week, set(absent) | {lead}) if lead else None
    b_now = (now or {}).get("points") or 0.0
    b_lead = (if_lead or {}).get("points") or 0.0
    return {"bump_now": round(b_now, 2), "bump_if_lead": round(b_lead, 2), "lead": lead,
            "lead_name": u.name_of.get(lead, lead) if lead else None, "bump": round(max(b_now, b_lead), 2),
            "out_now": [d["name"] for d in (now or {}).get("out") or []]}


def role_open(c):
    """True when the opportunity is real now: a teammate ahead of him is already out."""
    return bool(c) and (c.get("bump_now") or 0) >= ROLE_OPEN


def is_speculative(gap, ceiling_gain, bid):
    return gap >= SPEC_GAP or (ceiling_gain >= SPEC_GAIN and bid == 0)


def spec_bid(ceiling_gain, weeks_left, budget_left):
    cap = round(SPEC_BUDGET_SHARE * budget_left)
    raw = round(max(0.0, ceiling_gain) * weeks_left * 0.60 * SPEC_PROB)
    return max(1, min(cap, raw))


def describe(c, ros):
    if not c:
        return ""
    bits = []
    if c["bump_now"] > 0.05 and c["out_now"]:
        bits.append(f"{', '.join(c['out_now'][:2])} out now: about +{c['bump_now']:.1f} a week of vacated usage")
    if c["lead"] and c["bump_if_lead"] > c["bump_now"] + 0.05:
        bits.append(f"if {c['lead_name']} misses time: about +{c['bump_if_lead']:.1f} a week")
    if not bits:
        return "No role-change upside measured."
    return "; ".join(bits) + f". Ceiling {ros + c['bump']:.1f} a week vs {ros:.1f} expected."


class Book:
    """Ties the usage file to Sleeper ids and today's injury table. Built once per build."""

    def __init__(self, ctx, week):
        from .. import usage
        self.ok, self.reason = False, None
        self.season, self.week = int(ctx.season), week
        try:
            self.u, raw = usage.load(ctx.data_dir, ctx.season)
        except Exception as e:  # noqa: BLE001  the ceiling column must never take the build down
            self.u, raw, self.reason = None, {}, f"usage file could not be read ({e})"
        if self.u is None:
            self.reason = self.reason or "no data/usage file yet"
            return
        self.s2g = raw.get("sleeper_to_gsis") or {}
        from .recommend import set_current_teams
        set_current_teams(self.u, ctx, self.s2g)
        self.g2s = {g: s for s, g in self.s2g.items()}
        self.ctx = ctx
        self._absent = {}
        self.ok = True

    def team_code(self, team):
        from .recommend import SLEEPER_TO_NFLVERSE
        return SLEEPER_TO_NFLVERSE.get(team, team)

    def absent(self, team, pos):
        key = (team, pos)
        if key not in self._absent:
            out = set()
            for g in self.u.teammates(team, pos, self.season, self.week):
                sid = self.g2s.get(g)
                p = (self.ctx.players.get(sid) or {}) if sid else {}
                inj = self.ctx.injury(sid) if sid else {}
                if vc.is_absent((inj or {}).get("injury_status"), p.get("status")):
                    out.add(g)
            self._absent[key] = out
        return self._absent[key]

    def for_player(self, pid, pos, team):
        if not self.ok or pos not in POS or not team:
            return None
        g = self.s2g.get(pid)
        if not g:
            return None
        t = self.team_code(team)
        c = ceiling(self.u, g, t, pos, self.season, self.week, self.absent(t, pos))
        if c and c.get("lead"):
            c["lead_sleeper_id"] = self.g2s.get(c["lead"])
        return c
