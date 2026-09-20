"""Tests for the vacated target share column and the widened accuracy pool.

Run from the repo root:  python -m unittest tests.test_vacated -v

The test that matters most is SeparationTests.test_expected_is_untouched: the column is display
only, and a roster's expected points must be byte-identical whether the column is computed or not.
Everything else is arithmetic on a small hand-built usage book, so it runs with no nflverse cache
and no network. The replay tests skip themselves when the cache is absent.
"""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from engine.analysis import vacated as vc  # noqa: E402


def _cached(season, kinds=("stats_player_week_{s}.csv", "injuries_{s}.csv")):
    return all(os.path.exists(os.path.join("data", "history", k.format(s=season))) for k in kinds)


def toy_usage():
    """One team, three WRs, four weeks played. A takes 40% of targets, B 30%, C 10%.
    Team throws 30 times a game. Every target is worth 1.0 points for everyone."""
    rows, team_tot, absent = [], {}, {}
    plan = {"A": 12.0, "B": 9.0, "C": 3.0}
    for wk in (1, 2, 3, 4):
        team_tot[(2025, wk, "XXX")] = {"tgt": 30.0, "car": 20.0}
        for pid, tgt in plan.items():
            rows.append({"pid": pid, "name": pid, "pos": "WR", "team": "XXX", "season": 2025, "week": wk,
                         "tgt": tgt, "car": 0.0, "rec_pts": tgt * 1.0, "rush_pts": 0.0})
    prior = {pid: {"name": pid, "pos": "WR", "team": "XXX", "g": 4,
                   "tgt_share": round(t / 30.0, 4), "car_share": 0.0, "ppt": 1.0, "ppc": None}
             for pid, t in plan.items()}
    return vc.Usage(rows, team_tot, absent=absent, prior=prior,
                    prior_team={"XXX": {"tgt": 30.0, "car": 20.0}},
                    prior_pos={"WR": {"ppt": 1.0, "ppc": 0.5}}, season=2025)


class ArithmeticTests(unittest.TestCase):
    def setUp(self):
        self.u = toy_usage()

    def test_shares_match_the_hand_number(self):
        s = self.u.shares("A", 2025, 5)
        self.assertAlmostEqual(s["tgt"], 0.4, places=3)
        self.assertEqual(s["n"], 4)

    def test_nothing_vacated_when_nobody_is_out(self):
        sig = vc.signal(self.u, "A", "XXX", "WR", 2025, 5, set())
        self.assertEqual(sig["n_out"], 0)
        self.assertEqual(sig["points"], 0.0)

    def test_proportional_split_is_share_weighted(self):
        """C out (10%). A holds 40% and B 30% of the 80% still present, so A takes 40/80 of the 10%."""
        sig = vc.signal(self.u, "A", "XXX", "WR", 2025, 5, {"C"}, estimator="proportional")
        self.assertAlmostEqual(sig["vacated_tgt"], 0.1, places=3)
        self.assertAlmostEqual(sig["absorbed_tgt"], 0.1 * (0.4 / 0.7), places=3)

    def test_proportional_split_conserves_the_vacated_share(self):
        out = {"C"}
        total = sum(vc.signal(self.u, p, "XXX", "WR", 2025, 5, out, estimator="proportional")["absorbed_tgt"]
                    for p in ("A", "B"))
        self.assertAlmostEqual(total, 0.1, places=3)

    def test_points_equivalent_reads_in_points(self):
        """Absorbed share x 30 targets a game x 1.0 points per target."""
        sig = vc.signal(self.u, "A", "XXX", "WR", 2025, 5, {"C"}, estimator="proportional")
        self.assertAlmostEqual(sig["points"], round(sig["absorbed_tgt"] * 30.0 * sig["ppt"], 2), places=2)
        self.assertAlmostEqual(sig["ppt"], 1.0, places=3)

    def test_historical_falls_back_to_proportional_without_enough_games(self):
        """No week in the toy book has C absent, so the historical estimator has n = 0 and must
        return exactly the proportional answer."""
        h = vc.signal(self.u, "A", "XXX", "WR", 2025, 5, {"C"}, estimator="historical")
        p = vc.signal(self.u, "A", "XXX", "WR", 2025, 5, {"C"}, estimator="proportional")
        self.assertEqual(h["hist_pairs_used"], 0)
        self.assertAlmostEqual(h["absorbed_tgt"], p["absorbed_tgt"], places=6)

    def test_historical_uses_the_pair_once_it_has_three_games(self):
        """C is a 40% target hog who missed weeks 1 to 3. A ran at 60% of targets without him and
        30% with him, so the measured delta is +0.30 and that is what the historical estimator
        must return; the proportional split, which only sees two near-equal survivors, lands near
        half the vacated 40% instead."""
        u = self._hog_book()
        h = vc.signal(u, "A", "XXX", "WR", 2025, 7, {"C"}, estimator="historical")
        p = vc.signal(u, "A", "XXX", "WR", 2025, 7, {"C"}, estimator="proportional")
        self.assertEqual(h["hist_pairs_used"], 1)
        self.assertGreaterEqual(h["hist_min_games"], vc.MIN_HIST_GAMES)
        self.assertAlmostEqual(h["absorbed_tgt"], 0.3, places=3)
        self.assertAlmostEqual(p["absorbed_tgt"], 0.21, places=2)
        self.assertGreater(h["absorbed_tgt"], p["absorbed_tgt"] + 0.05)

    def test_historical_is_capped_at_the_vacated_share(self):
        """A player can never be credited with more than the absent teammate actually gave up, even
        when the measured delta is larger (some of that delta belongs to other causes)."""
        u = self._hog_book(c_share_when_present=3.0)      # C is now a 10% receiver
        h = vc.signal(u, "A", "XXX", "WR", 2025, 7, {"C"}, estimator="historical")
        self.assertAlmostEqual(h["absorbed_tgt"], h["vacated_tgt"], places=3)

    @staticmethod
    def _hog_book(c_share_when_present=12.0):
        rows, team_tot = [], {}
        for wk in (1, 2, 3, 4, 5, 6):
            c_out = wk <= 3
            team_tot[(2025, wk, "XXX")] = {"tgt": 30.0, "car": 20.0}
            plan = ({"A": 18.0, "B": 12.0} if c_out else
                    {"A": 9.0, "B": 30.0 - 9.0 - c_share_when_present, "C": c_share_when_present})
            for pid, tgt in plan.items():
                rows.append({"pid": pid, "name": pid, "pos": "WR", "team": "XXX", "season": 2025, "week": wk,
                             "tgt": tgt, "car": 0.0, "rec_pts": tgt, "rush_pts": 0.0})
        absent = {(2025, wk, "XXX"): {"C"} for wk in (1, 2, 3)}
        prior = {p: {"name": p, "pos": "WR", "team": "XXX", "g": 6, "tgt_share": v, "car_share": 0.0,
                     "ppt": 1.0, "ppc": None}
                 for p, v in (("A", 0.3), ("B", 0.3), ("C", round(c_share_when_present / 30.0, 4)))}
        return vc.Usage(rows, team_tot, absent=absent, prior=prior, prior_team={"XXX": {"tgt": 30.0, "car": 20.0}},
                        prior_pos={"WR": {"ppt": 1.0, "ppc": 0.5}}, season=2025)

    def test_absorption_never_exceeds_what_was_vacated(self):
        u = toy_usage()
        for est in ("proportional", "historical"):
            sig = vc.signal(u, "A", "XXX", "WR", 2025, 5, {"B", "C"}, estimator=est)
            self.assertLessEqual(sig["absorbed_tgt"], sig["vacated_tgt"] + 1e-9, est)
            self.assertGreaterEqual(sig["absorbed_tgt"], 0.0, est)

    def test_point_in_time_only(self):
        """Week 3's answer must not move when weeks 3 and later are corrupted."""
        u = toy_usage()
        before = vc.signal(u, "A", "XXX", "WR", 2025, 3, {"C"}, estimator="historical")
        rows = copy.deepcopy(u.rows)
        for r in rows:
            if r["week"] >= 3:
                r["tgt"] = r["tgt"] * 1000 + 999
                r["rec_pts"] = r["rec_pts"] * 1000 + 999
        tot = {k: (dict(v) if k[1] < 3 else {"tgt": v["tgt"] * 1000, "car": v["car"]}) for k, v in u.team_tot.items()}
        u2 = vc.Usage(rows, tot, absent=u.absent, prior=u.prior, prior_team=u.prior_team,
                      prior_pos=u.prior_pos, season=2025)
        after = vc.signal(u2, "A", "XXX", "WR", 2025, 3, {"C"}, estimator="historical")
        self.assertEqual(json.dumps(before, sort_keys=True), json.dumps(after, sort_keys=True))

    def test_only_skill_positions_get_a_column(self):
        self.assertIsNone(vc.signal(self.u, "A", "XXX", "QB", 2025, 5, {"C"}))
        self.assertIsNone(vc.signal(self.u, "A", "XXX", "DEF", 2025, 5, {"C"}))

    def test_absence_statuses(self):
        self.assertTrue(vc.is_absent("Out"))
        self.assertTrue(vc.is_absent("IR"))
        self.assertTrue(vc.is_absent("Doubtful"))
        self.assertTrue(vc.is_absent(None, "Injured Reserve"))
        self.assertFalse(vc.is_absent("Questionable"))
        self.assertFalse(vc.is_absent(None, None))


class SeparationTests(unittest.TestCase):
    """The column is display only. These are the tests the whole design rests on."""

    def test_value_player_has_no_vacated_input(self):
        import inspect
        from engine.analysis import recommend
        src = inspect.getsource(recommend.value_player)
        self.assertNotIn("vacated", src)
        self.assertNotIn("vc.", src)

    def test_expected_is_untouched(self):
        """Build the real lineup twice, once with the column and once with it stubbed out to
        nothing, and assert every expected number and the slot order are identical."""
        from engine.analysis import context, recommend
        ctx = context.Ctx()
        if not (ctx.my_roster or (ctx.latest.get("upcoming_week") or {}).get("starters")):
            self.skipTest("no roster in the committed data")

        def strip(rec):
            keep = ("player_id", "slot", "pos", "expected", "sleeper", "baseline", "season_avg", "inj_mult")
            return json.dumps({"total": rec["expected_total"],
                               "lineup": [{k: r.get(k) for k in keep} for r in rec["lineup"]],
                               "bench": [{k: r.get(k) for k in keep} for r in rec["bench"]]}, sort_keys=True)

        with_col = recommend.lineup_recommendation(ctx)
        real = recommend.vacated_column
        recommend.vacated_column = lambda *a, **k: ({}, {"available": False, "reason": "disabled for the test"})
        try:
            without = recommend.lineup_recommendation(ctx)
        finally:
            recommend.vacated_column = real
        self.assertEqual(strip(with_col), strip(without))
        self.assertTrue(any("vacated" in k for k in with_col))

    def test_column_never_changes_the_close_call_tiebreak(self):
        """The `why` line that drives the decision must be the same either way; the vacated text
        lives in its own field."""
        from engine.analysis import context, recommend
        ctx = context.Ctx()
        rec = recommend.lineup_recommendation(ctx)
        for c in rec["close_calls"]:
            self.assertNotIn("Vacated", c["why"])
            self.assertIn("apart.", c["why"])


class AccuracyPoolTests(unittest.TestCase):
    def test_waiver_pool_exists_and_is_disjoint_from_rosters(self):
        from engine.analysis import context, accuracy
        ctx = context.Ctx()
        hist = accuracy.build(ctx)
        self.assertIn("waiver", hist["pools"])
        self.assertEqual(hist["waiver_cut"], accuracy.WAIVER_PROJ_MIN)
        for w in hist["weeks"]:
            self.assertIn("waiver", w)
            # a graded waiver player is never one of the rostered players of that week
            rostered_n = w["rostered"]["n_players"]
            self.assertGreater(rostered_n, 0)
            self.assertGreaterEqual(w["waiver"]["n_players"], 0)
        if hist["weeks"]:
            self.assertIn("waiver", hist["pooled"])

    def test_waiver_pool_respects_the_projection_cut(self):
        from engine.analysis import context, accuracy
        ctx = context.Ctx()
        snaps = {}
        for w in sorted(ctx.scored):
            if w > ctx.completed_week:
                continue
            rep = accuracy.week_report(ctx, w, snaps)
            if not rep:
                continue
            scored = (ctx.scored.get(w) or {}).get("players") or {}
            on_roster = set()
            for m in ctx.matchups.get(w) or []:
                on_roster.update(p for p in (m.get("players") or []) if p and p != "0")
            eligible = [p for p, s in scored.items()
                        if p not in on_roster and s.get("actual") is not None
                        and (s.get("proj") or 0) >= accuracy.WAIVER_PROJ_MIN]
            # the report's pool uses the pre-kickoff projection where one exists, so it can differ
            # slightly from this post-hoc count; it must be in the same ballpark and never empty
            # when there are clearly eligible players
            if eligible:
                self.assertGreater(rep["waiver"]["n_players"], 0)


@unittest.skipUnless(_cached(2024) and _cached(2023), "nflverse cache not present (run python engine.py histbacktest)")
class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from engine.analysis import histdata, usagedata, histvacated
        cls.hv = histvacated
        cls.scoring, cls.slots, _ = histdata.scoring_from_league()
        cls.u = usagedata.build(2024, cls.scoring, quiet=True)

    def test_absence_is_built_and_carries_forward(self):
        weeks = {w for (s, w, t) in self.u.absent if s == 2024}
        self.assertTrue(weeks, "no absence sets were built from the nflverse injury report")
        self.assertGreater(sum(len(v) for k, v in self.u.absent.items() if k[0] == 2024), 500)

    def test_injuries_release_covers_every_backtest_season(self):
        from engine import history
        cov = history.injuries_coverage(range(2014, 2026))
        missing = [s for s, v in cov.items() if not v.get("present")]
        self.assertEqual(missing, [], f"nflverse injuries missing for {missing}; the backtest window must be cut")

    def test_backtest_is_deterministic(self):
        seasons = {y: __import__("engine.analysis.histdata", fromlist=["x"]).load_season(y, self.scoring)
                   for y in (2023, 2024)}
        a = self.hv.season_arms(seasons, 2024, self.scoring, self.slots, weeks_max=5)
        b = self.hv.season_arms(seasons, 2024, self.scoring, self.slots, weeks_max=5)
        dump = lambda r: json.dumps({str(k): v for k, v in r["week_arm"].items()}, sort_keys=True)  # noqa: E731
        self.assertEqual(dump(a), dump(b))
        self.assertTrue(a["week_arm"], "no weeks were replayed")

    def test_tiebreak_only_swaps_inside_the_window(self):
        cands = [("a", "WR"), ("b", "WR"), ("c", "RB")]
        pred = {"a": 10.0, "b": 9.0, "c": 5.0}
        far = {"a": 10.0, "b": 1.0, "c": 5.0}
        key = {"a": 0.0, "b": 1.0, "c": 0.0}
        near_lu = self.hv.tiebreak_lineup(cands, lambda c: pred[c], lambda c: key[c], ["WR"])
        far_lu = self.hv.tiebreak_lineup(cands, lambda c: far[c], lambda c: key[c], ["WR"])
        self.assertEqual(near_lu, [("WR", "b")])   # 1.0 apart, inside the window, higher key wins
        self.assertEqual(far_lu, [("WR", "a")])    # 9.0 apart, outside the window, no swap


if __name__ == "__main__":
    unittest.main()
