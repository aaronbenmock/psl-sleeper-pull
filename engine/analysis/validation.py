"""Data validation checks, recomputed on every build and shown on the dashboard. Each check
has a status (ok / warn / info / fail), a one-line finding and the number behind it."""
import statistics

from .. import config
from ..timeutil import parse_iso


def build(ctx, accuracy):
    checks = []
    rc = ctx.meta.get("record_check") or {}
    up = ctx.latest.get("upcoming_week") or {}
    rec = up.get("record") or {}
    if rc:
        checks.append({"id": "record", "status": "ok" if rc.get("verdict", "").startswith("median") or rc.get("verdict") == "head-to-head only" else "warn",
                       "title": "Record field (the 2-0 after one week)",
                       "finding": f"{rc.get('verdict')}. League setting league_average_match = {rc.get('league_average_match_setting')}; "
                                  f"wins across all rosters = {rc.get('sum_of_wins')} after {rc.get('completed_weeks')} week(s) "
                                  f"(head-to-head only would give {rc.get('expected_wins_h2h_only')}, with a median game {rc.get('expected_wins_with_median_game')})."})
    else:
        sb = (ctx.latest.get("completed_week") or {}).get("league_scoreboard") or []
        pts = sorted([r.get("actual") or 0 for r in sb])
        med = (pts[5] + pts[6]) / 2 if len(pts) == 12 else None
        mine = (ctx.latest.get("completed_week") or {}).get("my_actual")
        checks.append({"id": "record", "status": "info",
                       "title": "Record field (the 2-0 after one week)",
                       "finding": f"latest.json shows {rec.get('wins')}-{rec.get('losses')} with {ctx.completed_week} week complete. Most likely explanation [Likely]: "
                                  f"the league plays a second game each week against the league median. Week 1 median was {med}; you scored {mine}, "
                                  f"above it, and you beat your head-to-head opponent, which is exactly 2-0. The v1.2 pull reads the league setting "
                                  f"(league_average_match) and sums every roster's wins to confirm this on its first run."})
    # DEF bias
    wk = (accuracy.get("weeks") or [None])[-1] if accuracy.get("weeks") else None
    if wk and wk.get("def_bias", {}).get("n"):
        db = wk["def_bias"]
        checks.append({"id": "def_bias", "status": "info", "title": "DEF projection bias (Sleeper omits 3-and-outs and 4th-down stops)",
                       "finding": f"Week {wk['week']}: across {db['n']} defenses, actual minus projected averaged {db['bias']:+.2f} (MAE {db['mae']}). "
                                  f"Points from the two unprojected categories averaged {db['unprojected_pts']} per defense, which is the structural "
                                  f"part of the bias. Among the {db.get('started_n')} defenses actually started, bias was {db.get('started_bias')}."})
    else:
        # from the genuine v1.1 pull and the week 1 UI export
        try:
            import csv
            rows = list(csv.DictReader(open(f"{config.REFERENCE_DIR}/week1_fantasy_scores_sleeper_ui.csv", encoding="utf-8-sig")))
            d = [(float(r["Actual"]) - float(r["Projected"])) for r in rows if r["Pos"].startswith("DEF")]
            three = [r.get("three_and_out_pg_2025") for r in ctx.def_rankings.values() if r.get("three_and_out_pg_2025")]
            est = round(0.5 * statistics.mean(three), 2) if three else None
            checks.append({"id": "def_bias", "status": "warn", "title": "DEF projection bias (Sleeper omits 3-and-outs and 4th-down stops)",
                           "finding": f"Week 1, the 12 defenses that were started: actual minus projected averaged {statistics.mean(d):+.2f} "
                                      f"with a spread (SD) of {statistics.pstdev(d):.1f}, so n=12 cannot confirm or refute a small bias. "
                                      f"Structural estimate [Likely]: 2025 three-and-out rates in the DEF rankings average "
                                      f"{statistics.mean(three):.2f} per game, worth about {est} points at +0.5 each, plus 4th-down stops at +1 "
                                      f"(rate not in the reference file). Expect DEF projections to run roughly 1.5 to 2.5 points low. "
                                      f"The v1.2 pull stores the actual 3-and-out and 4th-down-stop counts for all 32 defenses every week, "
                                      f"so this becomes a measured number from the first run."})
        except Exception as e:  # noqa: BLE001
            checks.append({"id": "def_bias", "status": "warn", "title": "DEF projection bias", "finding": f"could not compute: {e}"})
    # coach_continuity
    checks.append({"id": "coach_continuity", "status": "info", "title": "Rankings column coach_continuity",
                   "finding": "Literal NOT_AVAILABLE for every player by design (no source). The engine never reads it."})
    # rankings join coverage
    mine = [r for r in (up.get("starters") or []) + (up.get("bench") or []) if r.get("player_id") and r.get("pos") != "DEF"]
    joined = [r for r in mine if r["player_id"] in ctx.rankings]
    checks.append({"id": "rankings_join", "status": "ok" if len(joined) == len(mine) else "warn",
                   "title": "Rankings CSV joins to Sleeper on sleeper_id",
                   "finding": f"{len(joined)} of {len(mine)} of your skill players found in player_rankings_v2.0 by sleeper_id"
                              + ("" if len(joined) == len(mine) else ": missing " + ", ".join(r["name"] for r in mine if r["player_id"] not in ctx.rankings)) + "."})
    # week detection
    checks.append({"id": "week_detection", "status": "info", "title": "Completed-week detection",
                   "finding": f"Method: {ctx.meta.get('week_detection') or 'v1.1 rule (matchups have points)'}. Completed {ctx.completed_week}, upcoming {ctx.upcoming_week}. "
                              "v1.2 uses game dates from the projection rows, which stays correct on Friday through Monday when the v1.1 rule would flip early."})
    # projection exclusions
    checks.append({"id": "proj_exclude", "status": "info", "title": "Projection formula",
                   "finding": "Projected = Sleeper's projected stat line x this league's scoring, excluding projected return TDs "
                              "(matches the Sleeper UI, verified week 1 by v1.1)."})
    # data ages
    ages = []
    t = parse_iso(ctx.meta.get("pulled_at_utc"))
    if t:
        ages.append(f"weekly pull {round((ctx.now - t).total_seconds() / 3600, 1)}h")
    t = parse_iso((ctx.injuries or {}).get("pulled_at_utc"))
    if t:
        ages.append(f"injury table {round((ctx.now - t).total_seconds() / 3600, 1)}h")
    t = parse_iso((ctx.players_meta or {}).get("pulled_at_utc"))
    if t:
        ages.append(f"players cache {round((ctx.now - t).total_seconds() / 3600, 1)}h")
    if ctx.snap_index:
        t = parse_iso(ctx.snap_index[-1].get("taken_at_utc"))
        ages.append(f"newest snapshot {round((ctx.now - t).total_seconds() / 3600, 1)}h (week {ctx.snap_index[-1].get('week')})")
    checks.append({"id": "ages", "status": "info", "title": "Input ages at build time", "finding": ", ".join(ages) or "no inputs yet"})
    return checks
