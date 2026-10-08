"""IR-slot eligibility check (engine/analysis/recommend.py ir_allowed / ir_ineligible).

Run from the repo root:  python -m unittest tests.test_ir -v
"""
import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from engine.analysis import recommend  # noqa: E402

# this league: Out, Doubtful and COVID allowed; Sus, DNR and NA not
CTX = SimpleNamespace(settings={"reserve_allow_out": 1, "reserve_allow_doubtful": 1, "reserve_allow_cov": 1,
                                "reserve_allow_sus": 0, "reserve_allow_dnr": 0, "reserve_allow_na": 0})


class IRTests(unittest.TestCase):
    def test_allowed_follows_league_settings(self):
        self.assertEqual(recommend.ir_allowed(CTX), ["IR", "PUP", "Out", "Doubtful", "COV"])

    def test_questionable_and_healthy_players_are_flagged(self):
        rows = [{"name": "Rico Dowdle", "injury_status": "Questionable"}, {"name": "Zach Charbonnet", "injury_status": "PUP"},
                {"name": "A", "injury_status": "Out"}, {"name": "B", "injury_status": None}, {"name": "C", "injury_status": "Sus"}]
        self.assertEqual([r["name"] for r in recommend.ir_ineligible(CTX, rows)], ["Rico Dowdle", "B", "C"])


if __name__ == "__main__":
    unittest.main()
