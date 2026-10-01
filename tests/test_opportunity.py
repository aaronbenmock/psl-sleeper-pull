"""Ceiling column, speculative claims, drop logic and the claims preferences.

Run from the repo root:  python -m unittest tests.test_opportunity -v

Arithmetic runs on the toy usage book from tests/test_vacated.py (three WRs: A 40%, B 30%, C 10% of
30 targets a game, 1.0 point per target). The integration tests build the real waiver recommendation
from the committed data twice and check that the new columns never move ros, gain or the engine bid.
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from engine.analysis import opportunity as op  # noqa: E402
from engine.analysis import recommend  # noqa: E402
from tests.test_vacated import toy_usage  # noqa: E402


class CeilingTests(unittest.TestCase):
    def setUp(self):
        self.u = toy_usage()

    def test_lead_is_the_healthy_teammate_with_more_usage(self):
        self.assertEqual(op.lead_teammate(self.u, "B", "XXX", "WR", 2025, 5, set()), "A")
        self.assertIsNone(op.lead_teammate(self.u, "A", "XXX", "WR", 2025, 5, set()))
        self.assertEqual(op.lead_teammate(self.u, "C", "XXX", "WR", 2025, 5, {"A"}), "B")

    def test_bump_if_lead_out_by_hand(self):
        """A out vacates 40%. B holds 30 of the 40 still present, so takes 30/40 of it: 30% x 30 x 1.0 = 9.0."""
        c = op.ceiling(self.u, "B", "XXX", "WR", 2025, 5, set())
        self.assertEqual(c["bump_now"], 0.0)
        self.assertAlmostEqual(c["bump_if_lead"], 9.0, places=1)
        self.assertEqual(c["bump"], c["bump_if_lead"])

    def test_role_open_now_counts_as_the_bump(self):
        c = op.ceiling(self.u, "B", "XXX", "WR", 2025, 5, {"A"})
        self.assertAlmostEqual(c["bump_now"], 9.0, places=1)
        self.assertTrue(op.role_open(c))

    def test_te_and_qb_get_no_ceiling(self):
        self.assertIsNone(op.ceiling(self.u, "A", "XXX", "TE", 2025, 5, set()))


class SpeculativeTests(unittest.TestCase):
    def test_flag_on_a_big_gap_or_a_big_gain_at_ceiling(self):
        self.assertTrue(op.is_speculative(4.0, 0.2, 3))
        self.assertTrue(op.is_speculative(1.0, 3.0, 0))
        self.assertFalse(op.is_speculative(1.0, 3.0, 5))     # already earns a real bid
        self.assertFalse(op.is_speculative(3.9, 2.9, 0))

    def test_spec_bid_is_capped_at_five_percent_and_at_least_one(self):
        self.assertEqual(op.spec_bid(20.0, 14, 200), 10)
        self.assertEqual(op.spec_bid(1.2, 14, 200), 3)        # 1.2 x 14 x 0.6 x 0.25 = 2.52
        self.assertEqual(op.spec_bid(0.0, 14, 200), 1)


class DropTests(unittest.TestCase):
    def m(self, pid, ros, injury=None, handcuff=False):
        return {"player_id": pid, "name": pid, "ros": ros, "injury_status": injury, "ros_how": "x", "team": "PIT",
                "handcuff": {"lead": "Jaylen Warren", "bump": 4.1} if handcuff else None}

    def test_injured_handcuff_is_held_when_a_healthy_lower_value_player_exists(self):
        allowed, held = recommend.handcuff_rule([self.m("Holani", 5.2), self.m("Dowdle", 8.4, "Questionable", True)])
        self.assertEqual([x["player_id"] for x in allowed], ["Holani"])
        self.assertIn("Dowdle", held)

    def test_injured_handcuff_stays_droppable_when_nothing_cheaper_is_healthy(self):
        allowed, held = recommend.handcuff_rule([self.m("Dowdle", 8.4, "Questionable", True), self.m("Hurt", 9.0, "Out")])
        self.assertEqual(held, {})
        self.assertEqual(len(allowed), 2)

    def test_healthy_handcuff_is_not_held(self):
        allowed, held = recommend.handcuff_rule([self.m("Holani", 5.2), self.m("Backup", 8.4, None, True)])
        self.assertEqual(held, {})

    def test_drop_reasons_name_the_handcuff_and_the_hold(self):
        r = recommend.drop_reasons(self.m("Dowdle", 8.4, "Questionable", True), 4, 11, False, "held back")
        self.assertTrue(any("handcuff: PIT backup to Jaylen Warren" in x for x in r))
        self.assertIn("held back", r)
        self.assertIn("not in this week's recommended lineup", r)


@unittest.skipUnless(os.path.exists(os.path.join("data", "latest.json")), "needs the committed data tree")
class RealDataTests(unittest.TestCase):
    """Built from whatever is committed, so these assert properties, not numbers."""

    @classmethod
    def setUpClass(cls):
        from engine.analysis.context import Ctx
        cls.ctx = Ctx("data")
        cls.lu = recommend.lineup_recommendation(cls.ctx)

    def run_w(self, prefs=None, no_ceiling=False):
        ctx = self.ctx
        old = ctx.prefs
        ctx.prefs = prefs or {"exclude_positions_from_claims": [], "faab_leftover_tendency": False}
        try:
            if no_ceiling:
                with mock.patch.object(op.Book, "for_player", return_value=None):
                    return recommend.waiver_recommendation(ctx, self.lu)
            return recommend.waiver_recommendation(ctx, self.lu)
        finally:
            ctx.prefs = old

    def test_ceiling_never_moves_ros_gain_or_engine_bid(self):
        """With the usage book switched off there are no ceilings and no handcuffs. ros must match for
        every claim; gain and the engine bid must match wherever the chosen drop is the same (the
        handcuff rule is allowed to change the drop, which is item 5 working as intended)."""
        a = {c["player_id"]: c for c in self.run_w()["claims"]}
        b = {c["player_id"]: c for c in self.run_w(no_ceiling=True)["claims"]}
        for pid in set(a) & set(b):
            self.assertEqual(a[pid]["ros"], b[pid]["ros"])
            if a[pid]["drop"]["player_id"] == b[pid]["drop"]["player_id"]:
                self.assertEqual((a[pid]["gain"], a[pid]["bid"]), (b[pid]["gain"], b[pid]["bid"]))

    def test_excluded_positions_leave_claims_for_the_collapsed_list(self):
        w = self.run_w({"exclude_positions_from_claims": ["TE"], "faab_leftover_tendency": True})
        self.assertFalse(any(c["pos"] == "TE" for c in w["claims"] + w["flyers"] + w["speculative"]))
        self.assertTrue(all(c["pos"] == "TE" for c in w["excluded_claims"]))
        self.assertEqual(w["excluded_positions"], ["TE"])

    def test_pace_setting_only_touches_the_league_bid(self):
        on = self.run_w({"exclude_positions_from_claims": [], "faab_leftover_tendency": True})
        off = self.run_w()
        self.assertEqual([c["bid"] for c in on["claims"]], [c["bid"] for c in off["claims"]])
        self.assertTrue(all(a["league_bid"] >= b["league_bid"] for a, b in zip(on["claims"], off["claims"])))

    def test_lineup_expected_is_untouched(self):
        again = recommend.lineup_recommendation(self.ctx)
        self.assertEqual([r.get("expected") for r in again["lineup"]], [r.get("expected") for r in self.lu["lineup"]])


if __name__ == "__main__":
    unittest.main()
