"""Tests for the historical harness (B8). Stdlib unittest; run from the repo root:

    python -m unittest tests.test_histbacktest -v

1. Scoring: hand-checked stat lines through the real league.json (all 88 settings), covering the
   yardage-bonus tiers, 40-plus TD bonuses, both fumble categories, return yards and the DEF line
   including three-and-outs, fourth-down stops and points allowed.
2. Leakage: corrupt the future weeks of a cached season and assert byte-identical predictions for
   the earlier weeks (skipped, not failed, if the nflverse cache is absent).
3. Determinism: two evaluations of the same season produce identical JSON.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from engine.analysis import psl_scoring as ps, histdata  # noqa: E402


def _cached(season):
    return (os.path.exists(os.path.join("data", "history", f"stats_player_week_{season}.csv"))
            and os.path.exists(os.path.join("data", "history", f"play_by_play_{season}.csv.gz")))


class ScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scoring, cls.slots, _ = histdata.scoring_from_league()

    def test_all_88_settings_read(self):
        self.assertEqual(len(self.scoring), 88)
        self.assertEqual(self.scoring["rec"], 0.5)
        self.assertEqual(self.scoring["pts_allow"], -0.1)
        self.assertEqual(self.scoring["def_3_and_out"], 0.5)
        self.assertEqual(self.scoring["def_4_and_stop"], 1.0)

    def test_offense_hand_checks(self):
        for row, extra, expected in ps.hand_check_cases():
            with self.subTest(row=row, extra=extra):
                self.assertAlmostEqual(ps.score_offense(row, extra, self.scoring), expected, places=2)

    def test_defense_hand_checks(self):
        for line, expected in ps.hand_check_defense_cases():
            with self.subTest(line=line):
                self.assertAlmostEqual(ps.score_defense(line, self.scoring), expected, places=2)

    def test_bonus_tiers_do_not_stack(self):
        self.assertAlmostEqual(ps.score_offense({"rushing_yards": "150"}, {}, self.scoring), 16.0)   # 15 + 1
        self.assertAlmostEqual(ps.score_offense({"rushing_yards": "200"}, {}, self.scoring), 22.0)   # 20 + 2, not + 3
        self.assertAlmostEqual(ps.score_offense({"passing_yards": "399"}, {}, self.scoring), 16.96)  # 15.96 + 1
        self.assertAlmostEqual(ps.score_offense({"passing_yards": "400"}, {}, self.scoring), 18.0)   # 16 + 2

    def test_negative_categories(self):
        self.assertAlmostEqual(ps.score_offense({"passing_interceptions": "3"}, {}, self.scoring), -6.0)
        self.assertAlmostEqual(ps.score_offense({"fumbles_total": "2", "fumbles_lost_total": "2"}, {}, self.scoring), -4.0)
        self.assertAlmostEqual(ps.score_defense({"pts_allow": 50}, self.scoring), -5.0)

    def test_slots_from_league(self):
        self.assertEqual(self.slots, ["QB", "RB", "RB", "WR", "WR", "FLEX", "FLEX", "DEF"])


@unittest.skipUnless(_cached(2024) and _cached(2023), "nflverse cache not present (run python engine.py histbacktest)")
class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from engine.analysis import histbacktest as hb, histmodels as hm
        cls.hb, cls.hm = hb, hm
        scoring, cls.slots, _ = histdata.scoring_from_league()
        cls.seasons = {y: histdata.load_season(y, scoring) for y in (2023, 2024)}
        cls.coefs = hm.fit_volume_coefs([cls.seasons[2023]])
        cls.models = ["naive", "kblend:4", "vol:0.5:4:0.1+opp:0.5:4:0.2", "ewk:0.1:4"]

    def test_leakage(self):
        r = self.hb.leakage_test(self.seasons, self.models, self.coefs, 2024, after_week=8)
        self.assertEqual(r["leaks"], [], f"predictions changed when future weeks were corrupted: {r['leaks']}")
        self.assertTrue(r["control_week_differs"], "corruption had no visible effect at all; the test is not exercising anything")
        self.assertTrue(r["passed"])

    def test_determinism(self):
        a = self.hb.eval_models(self.seasons, self.models, self.coefs, [2024], self.slots)
        b = self.hb.eval_models(self.seasons, self.models, self.coefs, [2024], self.slots)
        ja = json.dumps({m: self.hb.summarize(a[m]) for m in self.models}, sort_keys=True)
        jb = json.dumps({m: self.hb.summarize(b[m]) for m in self.models}, sort_keys=True)
        self.assertEqual(ja, jb)

    def test_gate_passes(self):
        if not _cached(2026):
            self.skipTest("2026 cache missing")
        g = histdata.gate()
        self.assertTrue(g["ok"], g.get("mismatches"))
        self.assertEqual(g["def"]["n_mismatch"], 0)


if __name__ == "__main__":
    unittest.main()
