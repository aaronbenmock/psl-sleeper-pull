"""Competitor threat per waiver target (engine/analysis/threats.py).

Run from the repo root:  python -m unittest tests.test_threats -v

Toy league modelled on week 4 of 2026: Amateur Hour owns De'Von Achane (MIA RB, IR), so they are the
natural Ollie Gordon bidder.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from engine.analysis import threats as th  # noqa: E402

GORDON = {"player_id": "12495", "name": "Ollie Gordon", "pos": "RB", "team": "MIA"}


def p(pid, name, pos, nfl, status=None, starter=False, lead=False, bye=False):
    return {"player_id": pid, "name": name, "pos": pos, "nfl": nfl, "status": status, "starter": starter,
            "lead": lead, "bye_next": bye}


def teams():
    return [
        {"roster_id": 1, "team": "Amateur Hour", "remaining": 193,
         "players": [p("9226", "De'Von Achane", "RB", "MIA", "IR", starter=False), p("a2", "RB Two", "RB", "BUF", starter=True),
                     p("a3", "RB Three", "RB", "NYG", starter=True)]},
        {"roster_id": 2, "team": "Healthy Deep", "remaining": 200,
         "players": [p(f"h{i}", f"RB {i}", "RB", "KC", starter=i < 2) for i in range(5)]},
        {"roster_id": 3, "team": "Broke", "remaining": 0,
         "players": [p("b1", "Hurt Starter", "RB", "DAL", "Out", starter=True)]},
        {"roster_id": 4, "team": "Hurt Starter", "remaining": 120,
         "players": [p("c1", "Starter RB", "RB", "DET", "Out", starter=True), p("c2", "Other", "RB", "SF", starter=True),
                     p("c3", "Bench", "RB", "LV")], "newly_out": ["Starter RB (Out)"]},
        {"roster_id": 8, "team": "ValKilmersComeback", "remaining": 200,
         "players": [p("x", "Mine", "RB", "MIA", "IR")]},
    ]


class ThreatTests(unittest.TestCase):
    def test_owner_of_the_injured_lead_ranks_first(self):
        top = th.likely_bidders(teams(), GORDON, my_rid=8)
        self.assertEqual(top[0]["team"], "Amateur Hour")
        self.assertTrue(any("Achane" in w for w in top[0]["why"]))
        self.assertEqual(top[0]["remaining"], 193)

    def test_teams_with_no_faab_and_aaron_are_never_listed(self):
        names = [b["team"] for b in th.likely_bidders(teams(), GORDON, my_rid=8)]
        self.assertNotIn("Broke", names)
        self.assertNotIn("ValKilmersComeback", names)

    def test_a_deep_healthy_team_is_not_a_threat(self):
        names = [b["team"] for b in th.likely_bidders(teams(), GORDON, my_rid=8)]
        self.assertNotIn("Healthy Deep", names)
        self.assertIn("Hurt Starter", names)

    def test_reasons_are_not_double_counted(self):
        s, why = th.score_team(teams()[0], GORDON)
        self.assertEqual(sum("Achane" in w for w in why), 1)
        self.assertEqual(s, 5)      # 4 for owning the absent MIA RB, 1 for only two healthy RBs

    def test_thin_depth_is_ignored_at_def(self):
        t = {"roster_id": 5, "team": "One DEF", "remaining": 100, "players": [p("SEA", "SEA DEF", "DEF", "SEA", starter=True)]}
        self.assertEqual(th.score_team(t, {"player_id": "LV", "name": "LV DEF", "pos": "DEF", "team": "LV"})[0], 0)


if __name__ == "__main__":
    unittest.main()
