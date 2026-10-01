"""League-calibrated bid (engine/analysis/bidding.py) and the budget-pace setting.

Run from the repo root:  python -m unittest tests.test_bidding -v
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from engine.analysis import bidding as bd  # noqa: E402
from engine.analysis.recommend import bid_size  # noqa: E402

GUIDE = {"by_pos": {"WR": {"n_wins": 5, "median_win": 7, "max_win": 26, "n_contested": 3, "median_contested": 12},
                    "RB": {"n_wins": 4, "median_win": 3.5, "max_win": 15, "n_contested": 0, "median_contested": None}},
         "most_contested": [{}, {}, {}], "most_contested_median": 20}


def row(run, name, pos, bid, n, winner="Be Safe", losing=()):
    return {"run": run, "processed": "Thu Sep 24 2:01 AM", "name": name, "pos": pos, "winning_bid": bid,
            "winner": winner, "n_bidders": n, "losing": [{"team": t, "bid": b} for t, b in losing]}


ROWS = [row(10, "Adonai Mitchell", "WR", 26, 3, losing=[("ScampDaddy", 16), ("tacocats", 0)]),
        row(10, "Caleb Filler", "WR", 4, 1), row(10, "X", "QB", 1, 1), row(10, "Y", "TE", 1, 1),
        row(12, "Michael Pittman", "WR", 6, 2, winner="ScampDaddy"),      # a two-claim Saturday trickle
        row(5, "Old WR", "WR", 40, 1)]


class PaceTests(unittest.TestCase):
    def test_full_budget_with_14_of_17_weeks_left_scales_by_1_21(self):
        f, why = bd.pace(200, 200, 14, 17, True)
        self.assertAlmostEqual(f, 1.21, places=2)
        self.assertIn("unspent", why)

    def test_setting_off_means_no_scaling(self):
        self.assertEqual(bd.pace(200, 200, 14, 17, False), (1.0, ""))

    def test_pace_is_capped_and_never_below_one(self):
        self.assertEqual(bd.pace(200, 200, 2, 17, True)[0], bd.PACE_CAP)
        self.assertEqual(bd.pace(20, 200, 14, 17, True)[0], 1.0)

    def test_projected_leftover_at_his_rate(self):
        self.assertEqual(bd.projected_leftover(200, 0, 3, 14), 200)
        self.assertEqual(bd.projected_leftover(170, 30, 3, 14), 30)


class MarketTests(unittest.TestCase):
    def test_comparable_tier_follows_the_bidder_count(self):
        self.assertEqual(bd.market_price("WR", 4, GUIDE)[0], 20)
        self.assertEqual(bd.market_price("WR", 2, GUIDE)[0], 12)
        self.assertEqual(bd.market_price("WR", 1, GUIDE)[0], 7)
        self.assertEqual(bd.market_price("RB", 2, GUIDE)[0], 3.5)    # no contested RB yet: falls back
        self.assertEqual(bd.market_price("TE", 1, GUIDE)[0], 1)

    def test_comparable_is_the_newest_weekly_runs_top_add(self):
        top, text = bd.comparable(ROWS, "WR")
        self.assertEqual(top["name"], "Adonai Mitchell")        # not the newer two-claim run, not the older $40
        self.assertIn("went $26", text)
        self.assertIn("3 bidders", text)

    def test_to_beat_clears_a_repeated_amount_by_two(self):
        amt, why = bd.to_beat([{"team": "Derrelick", "repeated": [31]}, {"team": "Cheeky", "repeated": [1], "pos_max": 12}], "TE")
        self.assertEqual(amt, 33)
        self.assertIn("Derrelick", why)

    def test_to_beat_uses_the_highest_bid_at_the_position(self):
        self.assertEqual(bd.to_beat([{"team": "Girth", "repeated": [], "pos_max": 15}], "RB")[0], 17)
        self.assertIsNone(bd.to_beat([{"team": "New", "repeated": []}], "RB")[0])


class LeagueBidTests(unittest.TestCase):
    def test_league_bid_never_exceeds_value_times_pace(self):
        b = bd.league_bid(0.8, 14, 200, 200, 17, True, "WR", [{}, {}, {}], GUIDE, ROWS)
        cap = bd.value_cap(0.8, 14, 200)
        self.assertAlmostEqual(cap, 6.72, places=2)
        self.assertEqual(b["league_bid"], round(cap * 1.21))
        self.assertIn("worth to you", b["league_bid_why"])

    def test_league_bid_is_the_market_when_value_is_higher(self):
        b = bd.league_bid(5.0, 14, 200, 200, 17, False, "WR", [{}], GUIDE, ROWS)
        self.assertEqual(b["league_bid"], 12)       # 2 bidders counting Aaron -> contested WR median

    def test_no_value_no_league_bid(self):
        self.assertEqual(bd.league_bid(0.3, 14, 200, 200, 17, True, "WR", [], GUIDE, ROWS)["league_bid"], 0)

    def test_original_engine_bid_is_unchanged(self):
        """The national-premium bid keeps its exact old arithmetic; the league bid is shown beside it."""
        bid, _ = bid_size(0.8, 14, 939252, 200, True, 12864768)
        raw = 0.8 * 14 * 0.6 * (1 + 0.5 * (939252 / 12864768) ** 0.5) * 1.15
        self.assertEqual(bid, int(round(raw)))


if __name__ == "__main__":
    unittest.main()
