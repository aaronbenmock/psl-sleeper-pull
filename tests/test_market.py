"""League FAAB market history (engine/analysis/market.py) and the names cache.

Run from the repo root:  python -m unittest tests.test_market -v

The fixture is a hand-built copy of two real waiver runs from 2026: the Thursday Sep 24 run, where
Derrelick won Travis Kelce at $31 over Aaron's $22, and a small earlier run where Derrelick won the
PIT DEF at $31 too, so his "usual" amount is $31.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from engine.analysis import market as mk  # noqa: E402
from engine import sleeper  # noqa: E402

# minute keys for the two runs (status_updated in ms)
RUN_A = 29_837_221 * 60_000 + 1_000     # Thu Sep 24 2026, 2:01 AM Central
RUN_B = 29_827_141 * 60_000 + 5_000     # Thu Sep 17 2026, 2:01 AM Central
NAMES = {"1466": ("Travis Kelce", "TE"), "PIT": ("PIT DEF", "DEF"), "777": ("Keenan Allen", "WR"),
         "888": ("Adonai Mitchell", "WR"), "999": ("Old Guy", "RB"), "555": ("Nobody Won", "RB")}
TEAMS = {1: "Derrelick my Balls", 2: "Cheeky Nando's", 3: "tacocats", 8: "ValKilmersComeback", 4: "Be Safe"}
DERRELICK, CHEEKY, TACO, AARON, JAX = 1, 2, 3, 8, 4


def tx(tid, status, rid, pid, bid, when, drops=None, notes=None):
    t = {"transaction_id": tid, "type": "waiver", "status": status, "roster_ids": [rid], "adds": {pid: rid},
         "drops": drops, "settings": {"waiver_bid": bid}, "status_updated": when}
    if notes:
        t["metadata"] = {"notes": notes}
    return t


def fixture():
    return {"3": [
        tx("a1", "complete", DERRELICK, "1466", 31, RUN_A, drops={"999": DERRELICK}),
        tx("a2", "failed", AARON, "1466", 22, RUN_A),
        tx("a3", "failed", CHEEKY, "1466", 12, RUN_A),
        tx("a4", "failed", TACO, "1466", 0, RUN_A),
        tx("a5", "complete", JAX, "888", 26, RUN_A),
        tx("a6", "failed", TACO, "888", 30, RUN_A, notes="Roster is full"),
        tx("a7", "failed", AARON, "555", 4, RUN_A),
    ], "2": [
        tx("b1", "complete", DERRELICK, "PIT", 31, RUN_B),
        tx("b2", "complete", AARON, "777", 3, RUN_B),
        tx("b3", "failed", CHEEKY, "777", 1, RUN_B),
        {"transaction_id": "fa", "type": "free_agent", "status": "complete", "adds": {"123": 2}, "status_updated": RUN_B},
    ]}


def info(pid):
    n, p = NAMES.get(pid, (f"Unknown player {pid}", None))
    return {"name": n, "pos": p}


def team(rid):
    return TEAMS.get(rid, f"roster {rid}")


class ClaimsTests(unittest.TestCase):
    def setUp(self):
        self.rows = mk.claims(fixture(), info, team)

    def row(self, name):
        return next(r for r in self.rows if r["name"] == name)

    def test_runs_are_grouped_by_processing_minute_not_week_key(self):
        self.assertEqual(len(mk.run_keys(self.rows)), 2)

    def test_free_agent_adds_are_not_waiver_claims(self):
        self.assertFalse(any(r["player_id"] == "123" for r in self.rows))

    def test_kelce_winner_losing_bids_and_bidder_count(self):
        k = self.row("Travis Kelce")
        self.assertEqual((k["winner"], k["winning_bid"], k["n_bidders"]), ("Derrelick my Balls", 31, 4))
        self.assertEqual([(lb["team"], lb["bid"]) for lb in k["losing"]],
                         [("ValKilmersComeback", 22), ("Cheeky Nando's", 12), ("tacocats", 0)])
        self.assertEqual(k["losing"][0]["reason"], "outbid")
        self.assertEqual(k["dropped"], ["Old Guy"])

    def test_a_failed_bid_above_the_winner_is_not_an_outbid(self):
        m = self.row("Adonai Mitchell")
        self.assertEqual(m["losing"][0]["bid"], 30)
        self.assertEqual(m["losing"][0]["reason"], "Roster is full")   # metadata reason wins when present
        rows = mk.claims({"1": [tx("x", "complete", 1, "888", 5, RUN_A), tx("y", "failed", 2, "888", 9, RUN_A)]}, info, team)
        self.assertIn("another reason", rows[0]["losing"][0]["reason"])

    def test_nobody_won_row(self):
        r = self.row("Nobody Won")
        self.assertIsNone(r["winner"])
        self.assertEqual(r["n_bidders"], 1)


class GuideAndTeamTests(unittest.TestCase):
    def setUp(self):
        self.rows = mk.claims(fixture(), info, team)

    def test_price_guide_medians_and_max(self):
        g = mk.price_guide(self.rows)
        wr = g["by_pos"]["WR"]
        self.assertEqual((wr["n_wins"], wr["median_win"], wr["max_win"]), (2, 14.5, 26))
        self.assertEqual(g["by_pos"]["TE"]["median_contested"], 31)

    def test_most_contested_per_run_and_median(self):
        g = mk.price_guide(self.rows)
        self.assertEqual([x["name"] for x in g["most_contested"]], ["Travis Kelce", "Keenan Allen"])
        self.assertEqual(g["most_contested_median"], 17)    # median of 31 and 3

    def test_usual_bid_is_the_repeated_amount(self):
        rosters = [{"roster_id": rid, "settings": {"waiver_budget_used": used}}
                   for rid, used in ((DERRELICK, 62), (AARON, 3), (CHEEKY, 0), (TACO, 0), (JAX, 26))]
        t = {x["roster_id"]: x for x in mk.team_table(self.rows, rosters, team)}
        self.assertEqual(t[DERRELICK]["usual_bid"], 31)
        self.assertEqual(t[DERRELICK]["repeated"], [31])
        self.assertEqual(t[DERRELICK]["biggest_win"], {"name": "Travis Kelce", "bid": 31})

    def test_spent_matches_waiver_budget_used(self):
        rosters = [{"roster_id": DERRELICK, "settings": {"waiver_budget_used": 62}},
                   {"roster_id": AARON, "settings": {"waiver_budget_used": 3}}]
        t = {x["roster_id"]: x for x in mk.team_table(self.rows, rosters, team)}
        self.assertTrue(t[DERRELICK]["log_matches"])
        self.assertEqual(t[DERRELICK]["remaining"], 138)
        self.assertEqual(t[AARON]["spent"], 3)


class AaronTests(unittest.TestCase):
    def setUp(self):
        self.rows = mk.claims(fixture(), info, team)

    def test_history_has_wins_and_losses_with_the_winning_bid(self):
        h = {b["name"]: b for b in mk.my_history(self.rows, AARON)}
        self.assertEqual(h["Keenan Allen"]["result"], "won")
        self.assertEqual((h["Travis Kelce"]["result"], h["Travis Kelce"]["winning_bid"], h["Travis Kelce"]["winner"]),
                         ("lost", 31, "Derrelick my Balls"))

    def test_latest_results_marks_each_bid(self):
        res = mk.latest_results(self.rows, AARON)
        self.assertEqual(sorted((b["name"], b["result"]) for b in res["bids"]),
                         [("Nobody Won", "lost"), ("Travis Kelce", "lost")])

    def test_latest_mine_skips_runs_without_his_bids(self):
        rows = self.rows + mk.claims({"9": [tx("z", "complete", CHEEKY, "999", 1, RUN_A + 3 * 86_400_000)]}, info, team)
        self.assertEqual(mk.latest_results(rows, AARON)["bids"], [])
        self.assertEqual(mk.latest_mine(rows, AARON)["run"], RUN_A // 60_000)


class NamesCacheTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_cache_keeps_a_player_after_he_leaves_the_players_file(self):
        players = {"999": {"full_name": "Old Guy", "position": "RB", "team": "NYG"}}
        sleeper.update_names_cache(self.d, players, {"999", "PIT"}, today="2026-09-20")
        missing = sleeper.update_names_cache(self.d, {}, {"999", "4242"}, today="2026-09-30")
        cache = sleeper.load_names_cache(self.d)
        self.assertEqual(cache["999"]["name"], "Old Guy")
        self.assertEqual(cache["999"]["last_seen"], "2026-09-20")
        self.assertEqual(cache["PIT"]["pos"], "DEF")
        self.assertEqual(missing, 1)

    def test_transaction_ids_cover_adds_and_drops(self):
        self.assertEqual(sleeper.transaction_player_ids(fixture()), {"1466", "999", "888", "555", "PIT", "777", "123"})

    def test_merge_transactions_replaces_by_id(self):
        by_week = {"4": [{"transaction_id": "t1", "status": "pending", "status_updated": 1}]}
        sleeper.merge_transactions(by_week, 4, [{"transaction_id": "t1", "status": "complete", "status_updated": 2},
                                                {"transaction_id": "t2", "status": "failed", "status_updated": 2}])
        self.assertEqual([(t["transaction_id"], t["status"]) for t in by_week["4"]], [("t1", "complete"), ("t2", "failed")])
        self.assertIn("metadata", by_week["4"][0])

    def test_ctx_resolves_a_cut_player_through_the_cache(self):
        os.makedirs(os.path.join(self.d, "players"))
        with open(os.path.join(self.d, "players", "names_cache.json"), "w") as f:
            json.dump({"players": {"31337": {"name": "Cut Player", "pos": "WR", "team": None}}}, f)
        from engine.analysis.context import Ctx
        ctx = Ctx(self.d)
        self.assertEqual(ctx.info("31337")["name"], "Cut Player")
        self.assertEqual(ctx.info("424242")["name"], "Unknown player 424242")
        self.assertTrue(ctx.resolvable("31337"))
        self.assertFalse(ctx.resolvable("424242"))


if __name__ == "__main__":
    unittest.main()
