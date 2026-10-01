"""League-calibrated FAAB bid, shown beside the engine's original bid (which is unchanged).

The original bid (recommend.bid_size) prices a claim from what it is worth to Aaron and then adds a
premium from national Sleeper add counts. This module answers the other question: what does it cost
to win this player in THIS league? It reads the market history (market.py) and the likely bidders
(threats.py) and never exceeds what the player is worth to Aaron.

  value_cap   = gain x weeks_left x $0.60, capped at 45% of the remaining budget (60% at 5+ pts)
                (the original formula without the national and early-season premiums)
  market      = this league's comparable price for the position at the expected bidder count:
                3+ likely bidders  median winning bid of each run's most-contested player
                2                  median contested winning bid at the position
                0 or 1             median winning bid at the position
  pace        = 1, or when faab_leftover_tendency is on:
                clamp((budget_left / budget_total) / (weeks_left / season_weeks), 1.0, 1.5)
  league_bid  = pace x min(value_cap, max(market, 1))
  to_beat     = the highest known amount among the likely bidders + $2, where known = an amount the
                team has bid two or more times, or its highest bid at this position

[Guessing] on the 1.5 pace cap, the $2 margin and the bidder tiers. The market sample is small (about
twenty completed claims after three waiver runs), so every comparable is quoted with its n.
"""
RATE = 0.60
PACE_CAP = 1.5
BEAT_MARGIN = 2
FULL_RUN = 4        # a run with this many claimed players is a weekly run, not a mid-week trickle


def value_cap(gain, weeks_left, budget_left):
    if gain is None or gain <= 0.5:
        return 0.0
    raw = gain * weeks_left * RATE
    cap = budget_left * (0.60 if gain >= 5 else 0.45)
    return min(raw, cap)


def pace(budget_left, budget_total, weeks_left, season_weeks, tendency):
    """Returns (factor, sentence)."""
    if not tendency or not budget_total or not season_weeks or weeks_left <= 0:
        return 1.0, ""
    ratio = (budget_left / budget_total) / (weeks_left / season_weeks)
    f = max(1.0, min(PACE_CAP, ratio))
    if f <= 1.0:
        return 1.0, ""
    return round(f, 2), (f"x{f:.2f} budget pace: ${budget_left} of ${budget_total} left with {weeks_left} of "
                         f"{season_weeks} weeks to go, and you usually finish with FAAB unspent, so bids are scaled "
                         f"up to spend it down toward $0")


def projected_leftover(budget_left, spent, weeks_elapsed, weeks_left):
    """End-of-season FAAB left if Aaron keeps spending at his season-to-date rate."""
    rate = (spent / weeks_elapsed) if weeks_elapsed else 0.0
    return max(0, round(budget_left - rate * weeks_left))


def market_price(pos, n_bidders, guide):
    """Returns (price, basis text)."""
    g = (guide.get("by_pos") or {}).get(pos) or {}
    if n_bidders >= 3 and guide.get("most_contested_median") is not None:
        n = len(guide.get("most_contested") or [])
        return max(1, guide["most_contested_median"]), f"median winning bid of each run's most-contested player (n={n})"
    if n_bidders >= 2 and g.get("median_contested") is not None:
        return max(1, g["median_contested"]), f"median contested {pos} winning bid (n={g['n_contested']})"
    if g.get("median_win") is not None:
        return max(1, g["median_win"]), f"median {pos} winning bid (n={g['n_wins']})"
    return 1, f"no {pos} claim has cleared in this league yet"


def comparable(rows, pos):
    """The newest weekly run's top winning add at this position (a run with FULL_RUN or more claimed
    players; a two-claim Saturday run is not a market), as a sentence and the row."""
    wins = [r for r in rows if r["pos"] == pos and r["winning_bid"] is not None]
    if not wins:
        return None, f"No {pos} has been won on waivers in this league yet."
    size = {}
    for r in rows:
        size[r["run"]] = size.get(r["run"], 0) + 1
    full = [r for r in wins if size[r["run"]] >= FULL_RUN]
    last_run = max(r["run"] for r in (full or wins))
    top = max((r for r in wins if r["run"] == last_run), key=lambda r: (r["winning_bid"], r["n_bidders"]))
    others = ", ".join(f"{lb['team']} ${lb['bid']}" for lb in top["losing"][:3])
    return top, (f"{top['processed'].split(' ')[0]} {' '.join(top['processed'].split(' ')[1:3])} run's top {pos} add: "
                 f"{top['name']} went ${top['winning_bid']} to {top['winner']} with {top['n_bidders']} bidder"
                 f"{'s' if top['n_bidders'] != 1 else ''}" + (f" (losing: {others})" if others else "") + ".")


def to_beat(bidders, pos=None):
    """bidders: [{"team", "repeated": [...], "pos_max"}]. Known amounts are the bids a team has filed two
    or more times, and its highest bid at this position. Returns (amount or None, text)."""
    best = None
    for b in bidders or []:
        known = [(a, "has bid ${:g} more than once") for a in (b.get("repeated") or [])]
        if b.get("pos_max"):
            known.append((b["pos_max"], "has bid as much as ${:g} on a " + (pos or "player")))
        for amt, how in known:
            if amt is None or amt <= 0:
                continue
            if best is None or amt > best[0]:
                best = (amt, b["team"], how)
    if not best:
        return None, "No likely bidder has a bidding pattern yet."
    amt = int(round(best[0])) + BEAT_MARGIN
    return amt, f"${amt}: ${BEAT_MARGIN} over {best[1]}, who {best[2].format(best[0])}"


def league_bid(gain, weeks_left, budget_left, budget_total, season_weeks, tendency, pos, bidders, guide, rows):
    cap = value_cap(gain, weeks_left, budget_left)
    f, pace_why = pace(budget_left, budget_total, weeks_left, season_weeks, tendency)
    n = len(bidders or []) + 1
    price, basis = market_price(pos, n, guide)
    comp_row, comp_text = comparable(rows, pos)
    beat, beat_why = to_beat(bidders, pos)
    if cap <= 0:
        bid, why = 0, "worth under half a point a week to you, so no league bid either"
    else:
        base = min(cap, price)
        bid = int(round(min(base * f, budget_left)))
        bid = max(bid, 1)
        why = (f"${price:g} market ({basis}, {n} likely bidder{'s' if n != 1 else ''} counting you)"
               + (f", held to ${cap:.0f}, what he is worth to you" if cap < price else f", under your ${cap:.0f} value")
               + (f"; {pace_why}" if pace_why else ""))
    beat_ok = beat is not None and cap > 0 and beat <= cap * f
    return {"league_bid": bid, "league_bid_why": why, "value_cap": int(round(cap)), "market": price,
            "market_basis": basis, "pace": f, "comparable": comp_text,
            "comparable_bid": comp_row["winning_bid"] if comp_row else None,
            "to_beat": beat, "to_beat_why": beat_why,
            "to_beat_within_value": beat_ok if beat is not None else None}
