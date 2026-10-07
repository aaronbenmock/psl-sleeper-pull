"""Head-to-head card (engine/analysis/h2h.py) and the calls scorecard (engine/analysis/calls.py).

Run from the repo root:  python -m unittest tests.test_h2h_calls -v
"""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from engine.analysis import h2h, calls  # noqa: E402
from engine.timeutil import parse_iso  # noqa: E402


class H2HTests(unittest.TestCase):
    def test_opponent_is_the_other_roster_in_the_matchup(self):
        m = [{"roster_id": 8, "matchup_id": 3}, {"roster_id": 5, "matchup_id": 3}, {"roster_id": 1, "matchup_id": 1}]
        self.assertEqual(h2h.opponent_rid(m, 8), 5)
        self.assertIsNone(h2h.opponent_rid(m, 9))
        self.assertIsNone(h2h.opponent_rid([{"roster_id": 8, "matchup_id": None}], 8))

    def test_verdict_bands(self):
        self.assertEqual(h2h.verdict(101.9, 91.5), ("favored", 10.4))
        self.assertEqual(h2h.verdict(90.0, 101.0), ("underdog", -11.0))
        self.assertEqual(h2h.verdict(100.0, 96.0)[0], "toss-up")
        self.assertEqual(h2h.verdict(100.0, 105.0)[0], "toss-up")
        self.assertEqual(h2h.verdict(None, 90.0), ("unknown", None))


def lineup_rec(started=False):
    return {"lineup": [{"slot": "WR", "player_id": "boston", "name": "Denzel Boston", "expected": 9.4, "started": started},
                       {"slot": "QB", "player_id": "allen", "name": "Josh Allen", "expected": 23.3, "started": False}],
            "bench": [{"slot": "BN", "player_id": "metcalf", "name": "DK Metcalf", "expected": 8.3, "started": started}],
            "changes": [], "close_calls": [{"slot": "WR", "starter": "Denzel Boston", "bench": "DK Metcalf"}]}


WAIVERS = {"claims": [{"player_id": "LV", "name": "LV DEF", "pos": "DEF", "bid": 8, "league_bid": 7,
                       "drop": {"player_id": "SEA", "name": "SEA DEF"}},
                      {"player_id": "ka", "name": "Keenan Allen", "pos": "WR", "bid": 9, "league_bid": 8,
                       "drop": {"player_id": "holani", "name": "George Holani"}}],
           "speculative": []}
WED = parse_iso("2026-09-30T16:00:00Z")


class RecordTests(unittest.TestCase):
    def test_next_waiver_run_is_thursday_2am_central(self):
        self.assertEqual(calls.next_waiver_run(WED), parse_iso("2026-10-01T07:00:00Z"))

    def test_rows_freeze_once_a_player_kicks_off(self):
        first = calls.merge({}, 4, WED, lineup_rec(started=True), WAIVERS, None)
        self.assertTrue(first["start_sit"][0]["frozen"])
        # a later build with a different recommendation must not rewrite the frozen call
        later = lineup_rec(started=True)
        later["close_calls"] = [{"slot": "WR", "starter": "DK Metcalf", "bench": "Denzel Boston"}]
        second = calls.merge(first, 4, WED + dt.timedelta(hours=30), later, WAIVERS, None)
        self.assertEqual(second["start_sit"][0]["name"], "Denzel Boston")
        self.assertEqual(second["lineup"][0]["player_id"], "boston")

    def test_freeze_keeps_the_last_pre_kickoff_call(self):
        # Wednesday: Boston over Metcalf, nobody has played. Friday (after Thursday night): the engine
        # re-ranks and now prefers Metcalf. The graded call must be Wednesday's, frozen at Wednesday's build.
        first = calls.merge({}, 4, WED, lineup_rec(), WAIVERS, None)
        later = lineup_rec(started=True)
        later["lineup"][0] = dict(later["lineup"][0], player_id="metcalf", name="DK Metcalf")
        later["bench"] = [{"slot": "BN", "player_id": "boston", "name": "Denzel Boston", "expected": 9.4, "started": True}]
        later["close_calls"] = [{"slot": "WR", "starter": "DK Metcalf", "bench": "Denzel Boston"}]
        second = calls.merge(first, 4, WED + dt.timedelta(hours=40), later, WAIVERS, None)
        self.assertEqual([c["name"] for c in second["start_sit"]], ["Denzel Boston"])
        self.assertEqual(second["start_sit"][0]["frozen_at_utc"], first["updated_utc"])
        self.assertEqual(second["lineup"][0]["player_id"], "boston")
        self.assertTrue(second["lineup"][0]["frozen"])
        self.assertFalse(second["lineup"][1]["frozen"])         # Allen has not played yet
        g = calls.grade_start_sit(second["start_sit"][0], SCORED, set(), second["start_sit"][0]["frozen_at_utc"])
        self.assertTrue(g["graded"])

    def test_live_rows_are_replaced_until_kickoff(self):
        first = calls.merge({}, 4, WED, lineup_rec(), WAIVERS, None)
        later = lineup_rec()
        later["close_calls"] = []
        self.assertEqual(calls.merge(first, 4, WED + dt.timedelta(hours=2), later, WAIVERS, None)["start_sit"], [])

    def test_claims_freeze_at_the_waiver_run(self):
        first = calls.merge({}, 4, WED, lineup_rec(), WAIVERS, None)
        self.assertFalse(first.get("claims_frozen"))
        after = calls.merge(first, 4, parse_iso("2026-10-01T12:00:00Z"), lineup_rec(), {"claims": [], "speculative": []}, None)
        self.assertTrue(after["claims_frozen"])
        self.assertEqual(len(after["claims"]), 2)      # Wednesday's claims, not Thursday's empty list
        self.assertEqual(after["claims"][0]["type"], "def_stream")

    def test_synthesis_calls_only_for_the_same_week(self):
        meta = {"week": 4, "calls": [{"type": "start", "name": "Josh Allen"}]}
        self.assertEqual(len(calls.merge({}, 4, WED, lineup_rec(), WAIVERS, meta)["synthesis"]), 1)
        self.assertNotIn("synthesis", calls.merge({}, 5, WED, lineup_rec(), WAIVERS, meta))


SCORED = {"players": {"boston": {"actual": 7.1, "date": "2026-10-01"}, "metcalf": {"actual": 10.6, "date": "2026-10-01"},
                      "LV": {"actual": 3.0, "date": "2026-10-04"}, "SEA": {"actual": 9.0, "date": "2026-10-04"},
                      "ka": {"actual": 15.0, "date": "2026-10-04"}, "holani": {"actual": 4.0, "date": "2026-10-04"}}}


class GradeTests(unittest.TestCase):
    def test_start_sit_hit_miss_and_followed(self):
        c = {"type": "start_sit", "player_id": "boston", "alt_id": "metcalf"}
        g = calls.grade_start_sit(c, SCORED, {"boston"}, "2026-09-30T16:00:00Z")
        self.assertEqual((g["graded"], g["hit"], g["followed"]), (True, False, True))
        g = calls.grade_start_sit(dict(c, player_id="metcalf", alt_id="boston"), SCORED, {"boston"}, "2026-09-30T16:00:00Z")
        self.assertEqual((g["hit"], g["followed"]), (True, False))

    def test_a_call_made_after_kickoff_is_not_graded(self):
        c = {"type": "start_sit", "player_id": "boston", "alt_id": "metcalf"}
        self.assertFalse(calls.grade_start_sit(c, SCORED, set(), "2026-10-02T16:00:00Z")["graded"])

    def test_def_stream_is_one_week_and_strict(self):
        c = {"type": "def_stream", "player_id": "LV", "alt_id": "SEA"}
        g = calls.grade_claim(c, {4: SCORED, 5: SCORED}, 4, 5, {}, None)
        self.assertEqual((g["n_weeks"], g["hit"], g["aaron_bid"]), (1, False, None))

    def test_claim_sums_every_week_since_and_reads_the_bid(self):
        c = {"type": "claim", "player_id": "ka", "alt_id": "holani"}
        bids = {"ka": {"my_bid": 9, "result": "lost", "winning_bid": 14, "winner": "RafiBomb"}}
        g = calls.grade_claim(c, {4: SCORED, 5: SCORED}, 4, 5, bids, None)
        self.assertEqual((g["n_weeks"], g["actual"], g["alt_actual"], g["hit"]), (2, 30.0, 8.0, True))
        self.assertEqual((g["aaron_bid"], g["aaron_won"], g["winner"]), (9, False, "RafiBomb"))

    def test_hit_rates_by_type_and_source(self):
        weeks = [{"rows": [{"type": "start_sit", "source": "engine", "graded": True, "hit": True, "followed": True},
                           {"type": "start_sit", "source": "engine", "graded": True, "hit": False, "followed": False},
                           {"type": "claim", "source": "engine", "graded": True, "hit": True, "aaron_bid": 9},
                           {"type": "claim", "source": "synthesis", "graded": True, "hit": False, "aaron_bid": None},
                           {"type": "claim", "source": "engine", "graded": False}]}]
        hr = {(t["type"], t["source"]): t for t in calls.hit_rates(weeks)}
        self.assertEqual((hr[("start_sit", "engine")]["hit_rate"], hr[("start_sit", "engine")]["followed"]), (0.5, 1))
        self.assertEqual((hr[("claim", "engine")]["n"], hr[("claim", "engine")]["followed"]), (1, 1))
        self.assertEqual(hr[("claim", "synthesis")]["followed"], 0)


if __name__ == "__main__":
    unittest.main()
