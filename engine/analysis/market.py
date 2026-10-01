"""League FAAB market history, from data/league/transactions.json. How THIS league bids.

Sleeper's transaction log keeps every waiver claim, including the failed ones, with its bid. So for
every player claimed in a waiver run we know the winner, the winning bid, and every losing bid.

A waiver run is every claim processed in the same minute (`status_updated`). The log's week key is
not used for this: Sleeper files a claim under the week it was made, which is not the week it ran.

Caveat [Certain]: a claim can fail for reasons other than being outbid (the roster was full after an
earlier claim, the team ran out of budget, a tie lost on waiver priority). Sleeper writes the reason
into `metadata.notes`, which the pull only keeps from 2026-10 onward. A losing bid higher than the
winning bid is therefore flagged as "failed for another reason" rather than read as an outbid.
All functions are pure: they take plain data and two name lookups, so the tests need no files.
"""
import datetime as dt
import statistics
from collections import Counter, defaultdict

from ..sleeper import transaction_player_ids
from ..timeutil import to_central, iso


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _when(ms):
    t = dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc)
    return t, to_central(t).strftime("%a %b %d %I:%M %p").replace(" 0", " ")


def claims(tx_by_week, info, team_name):
    """One row per (waiver run, claimed player). info(pid) -> {"name", "pos"}; team_name(rid) -> str."""
    runs = defaultdict(list)
    for rows in (tx_by_week or {}).values():
        for t in rows or []:
            if t.get("type") != "waiver" or not t.get("adds") or not t.get("status_updated"):
                continue
            runs[int(t["status_updated"]) // 60000].append(t)
    out = []
    for key in sorted(runs):
        by_player = defaultdict(list)
        for t in runs[key]:
            for pid, rid in (t.get("adds") or {}).items():
                by_player[pid].append((t, rid))
        when, label = _when(key * 60000)
        for pid, claims_ in by_player.items():
            win = next(((t, rid) for t, rid in claims_ if t.get("status") == "complete"), None)
            win_bid = ((win[0].get("settings") or {}).get("waiver_bid") or 0) if win else None
            losing = {}
            for t, rid in claims_:
                if win and t is win[0]:
                    continue
                bid = (t.get("settings") or {}).get("waiver_bid") or 0
                note = ((t.get("metadata") or {}).get("notes") or "").strip()
                if note:
                    reason = note
                elif win is not None and bid > win_bid:
                    reason = "failed for another reason (bid was above the winning bid: roster limit, budget or an earlier claim)"
                elif win is not None and bid == win_bid:
                    reason = "tied the winning bid, lost on waiver priority [Likely]"
                elif win is not None:
                    reason = "outbid"
                else:
                    reason = "nobody won him; reason not recorded"
                if rid not in losing or bid > losing[rid]["bid"]:
                    losing[rid] = {"roster_id": rid, "team": team_name(rid), "bid": bid, "reason": reason}
            inf = info(pid)
            drops = []
            if win:
                drops = [info(d)["name"] for d in (win[0].get("drops") or {})]
            out.append({
                "run": key, "processed_utc": iso(when), "processed": label,
                "player_id": pid, "name": inf["name"], "pos": inf["pos"],
                "winner_rid": win[1] if win else None, "winner": team_name(win[1]) if win else None,
                "winning_bid": win_bid, "dropped": drops,
                "losing": sorted(losing.values(), key=lambda x: -x["bid"]),
                "n_bidders": (1 if win else 0) + len(losing),
            })
    out.sort(key=lambda r: (-r["run"], -(r["n_bidders"]), -(r["winning_bid"] or 0)))
    return out


def run_keys(rows):
    return sorted({r["run"] for r in rows}, reverse=True)


def most_contested(rows):
    """Per run, the claimed player with the most bidders (ties: higher winning bid). Runs with no
    player drawing two or more bidders have no most-contested player."""
    best = {}
    for r in rows:
        if r["winning_bid"] is None or r["n_bidders"] < 2:
            continue
        cur = best.get(r["run"])
        if cur is None or (r["n_bidders"], r["winning_bid"]) > (cur["n_bidders"], cur["winning_bid"]):
            best[r["run"]] = r
    return [best[k] for k in sorted(best, reverse=True)]


def price_guide(rows, positions=("QB", "RB", "WR", "TE", "DEF")):
    guide = {}
    for pos in positions:
        wins = [r for r in rows if r["pos"] == pos and r["winning_bid"] is not None]
        cont = [r for r in wins if r["n_bidders"] >= 2]
        guide[pos] = {"n_wins": len(wins),
                      "median_win": _median([r["winning_bid"] for r in wins]),
                      "max_win": max([r["winning_bid"] for r in wins], default=None),
                      "n_contested": len(cont),
                      "median_contested": _median([r["winning_bid"] for r in cont]),
                      "max_contested": max([r["winning_bid"] for r in cont], default=None)}
    mc = most_contested(rows)
    return {"by_pos": guide, "most_contested": [{k: r[k] for k in ("processed", "name", "pos", "winner", "winning_bid", "n_bidders")} for r in mc],
            "most_contested_median": _median([r["winning_bid"] for r in mc])}


def team_bids(rows):
    """{roster_id: [bids]} with every bid a team filed, won or lost (one per player per run)."""
    out = defaultdict(list)
    for r in rows:
        if r["winner_rid"] is not None:
            out[r["winner_rid"]].append(r["winning_bid"])
        for lb in r["losing"]:
            out[lb["roster_id"]].append(lb["bid"])
    return out


def usual_bid(bids, wins):
    """The amount a team keeps coming back to: the most frequent nonzero bid filed two or more times
    (ties go to the higher amount); otherwise the median winning bid. Returns (amount, how)."""
    c = Counter(b for b in bids if b and b > 0)
    rep = sorted(((n, amt) for amt, n in c.items() if n >= 2), reverse=True)
    if rep:
        return rep[0][1], f"bid ${rep[0][1]} {rep[0][0]} times"
    m = _median(wins)
    return (m, "median winning bid") if m is not None else (None, "no wins yet")


def team_table(rows, rosters, team_name, budget_total=200):
    bids = team_bids(rows)
    table = []
    for r in rosters or []:
        rid = r["roster_id"]
        mine = [x for x in rows if x["winner_rid"] == rid]
        wins = [x["winning_bid"] for x in mine]
        spent_log = sum(wins)
        used = (r.get("settings") or {}).get("waiver_budget_used")
        spent = used if used is not None else spent_log
        big = max(mine, key=lambda x: x["winning_bid"], default=None)
        n_claims = len(mine) + sum(1 for x in rows for lb in x["losing"] if lb["roster_id"] == rid)
        amt, how = usual_bid(bids.get(rid, []), wins)
        repeated = sorted({b for b, n in Counter(b for b in bids.get(rid, []) if b).items() if n >= 2}, reverse=True)
        table.append({"roster_id": rid, "team": team_name(rid), "spent": spent, "spent_in_log": spent_log,
                      "log_matches": spent == spent_log, "remaining": budget_total - spent,
                      "n_claims": n_claims, "n_wins": len(mine),
                      "biggest_win": {"name": big["name"], "bid": big["winning_bid"]} if big else None,
                      "usual_bid": amt, "usual_how": how, "repeated": repeated})
    table.sort(key=lambda t: (-t["spent"], t["team"]))
    return table


def my_history(rows, my_rid):
    out = []
    for r in rows:
        if r["winner_rid"] == my_rid:
            out.append({"processed": r["processed"], "run": r["run"], "name": r["name"], "pos": r["pos"], "result": "won",
                        "my_bid": r["winning_bid"], "winning_bid": r["winning_bid"], "winner": r["winner"],
                        "n_bidders": r["n_bidders"], "next_best": r["losing"][0]["bid"] if r["losing"] else None})
            continue
        lb = next((x for x in r["losing"] if x["roster_id"] == my_rid), None)
        if lb:
            out.append({"processed": r["processed"], "run": r["run"], "name": r["name"], "pos": r["pos"], "result": "lost",
                        "my_bid": lb["bid"], "winning_bid": r["winning_bid"], "winner": r["winner"],
                        "n_bidders": r["n_bidders"], "reason": lb["reason"]})
    return out


def latest_results(rows, my_rid, since_utc=None):
    """Aaron's bids in the newest waiver run (optionally only a run processed after `since_utc`).
    Returns None when there is no such run."""
    keys = run_keys(rows)
    if since_utc is not None:
        keys = [k for k in keys if k * 60000 / 1000 >= since_utc.timestamp()]
    if not keys:
        return None
    key = keys[0]
    in_run = [r for r in rows if r["run"] == key]
    mine = my_history(in_run, my_rid)
    return {"run": key, "processed": in_run[0]["processed"], "processed_utc": in_run[0]["processed_utc"],
            "n_claims_league": sum(r["n_bidders"] for r in in_run), "bids": mine}


def latest_mine(rows, my_rid):
    """Aaron's bids in the newest run he took part in (None if he never bid)."""
    mine = my_history(rows, my_rid)
    if not mine:
        return None
    key = max(m["run"] for m in mine)
    return {"run": key, "processed": next(m["processed"] for m in mine if m["run"] == key),
            "bids": [m for m in mine if m["run"] == key]}


def build(ctx):
    rows = claims(ctx.transactions, ctx.info, ctx.team_name)
    budget_total = (ctx.latest.get("upcoming_week") or {}).get("waiver_budget_total") or ctx.settings.get("waiver_budget") or 200
    all_ids = transaction_player_ids(ctx.transactions)
    return {"claims": rows, "price_guide": price_guide(rows),
            "teams": team_table(rows, ctx.rosters, ctx.team_name, budget_total),
            "mine": my_history(rows, ctx.my_rid), "latest": latest_results(rows, ctx.my_rid),
            "latest_mine": latest_mine(rows, ctx.my_rid),
            "budget_total": budget_total, "n_runs": len(run_keys(rows)),
            "ids_total": len(all_ids), "ids_unresolved": sorted(p for p in all_ids if not ctx.resolvable(p)),
            "note": ("Losing bids come from Sleeper's failed-claim records. A failed claim above the winning bid failed for "
                     "another reason (roster limit, budget, an earlier claim), so it is not read as an outbid. Failure "
                     "reasons are only recorded from October 2026 on.")}
