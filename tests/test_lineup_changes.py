import unittest

from engine.analysis import context, recommend


def _v(pid, name, pos, expected, playing=True, bye=False):
    return {"player_id": pid, "name": name, "pos": pos, "expected": expected, "playing": playing, "bye": bye,
            "injury_status": None, "injury_body_part": None, "inj_mult": 1.0, "sleeper": expected,
            "baseline": None, "n_games": 0, "season_avg": None, "preseason": None, "opp": None}


class ChangesTests(unittest.TestCase):
    def test_benching_a_starter_on_bye_explains_why(self):
        """Week 8 2026: a starter on bye (Woody Marks) crashed the build with KeyError 'why',
        because the swap text read the raw values, which never carry a `why`."""
        vals = {"t1": _v("t1", "Starter On Bye", "RB", 0.0, playing=False, bye=True),
                "t2": _v("t2", "Bench Back", "RB", 7.9)}
        ctx = context.Ctx()
        ctx.my_roster = {"players": ["t1", "t2"], "reserve": [], "starters": ["t1"]}
        ctx.slots = ["RB"]
        saved = (recommend.value_player, recommend.vacated_column)
        recommend.value_player = lambda ctx, pid, week, proj: dict(vals[pid])
        recommend.vacated_column = lambda *a, **k: ({}, {"available": False})
        try:
            rec = recommend.lineup_recommendation(ctx)
        finally:
            recommend.value_player, recommend.vacated_column = saved
        self.assertEqual(len(rec["changes"]), 1)
        self.assertEqual(rec["changes"][0]["in"], "Bench Back")
        self.assertIn("On bye week", rec["changes"][0]["why"])


if __name__ == "__main__":
    unittest.main()
