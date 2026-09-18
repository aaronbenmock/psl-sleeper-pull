"""PSL scoring reconstruction: turn an nflverse stat line into Sleeper stat keys and apply the
league's scoring_settings (all 88 keys, read from data/league/league.json, never hand-typed).

Offense (from stats_player_week columns plus play-by-play extras):
  pass_yd, pass_td, pass_int, pass_2pt, bonus_pass_yd_300/400, pass_td_40p
  rush_yd, rush_td, rush_2pt, bonus_rush_yd_100/200, rush_td_40p
  rec, rec_yd, rec_td, rec_2pt, bonus_rec_yd_100/200, rec_td_40p
  fum, fum_lost, fum_rec, fum_rec_td, kr_yd, pr_yd, kr_td, pr_td, st_td
Yardage bonuses are tiers, not stacks: 300 to 399 passing yards pays bonus_pass_yd_300 only and
400 plus pays bonus_pass_yd_400 only (Tyler Shough, 410 yards in week 1 2026, scored 30.2 on
Sleeper, which only the tiered reading reproduces). The 100/200 rushing and receiving tiers are
treated the same way [Likely: no 200-yard game in the week-1 check]. Every mapping choice here was
checked against Sleeper's real week-1 2026 points by the gate in histbacktest (offense within 0.1).

Defense: the Sleeper-keyed line built by analysis/pbp.py, scored with the same function.
"""


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def offense_line(row, extra=None):
    """nflverse weekly row (dict of strings) + pbp extras -> Sleeper stat keys."""
    e = extra or {}
    py, ry, cy = _f(row.get("passing_yards")), _f(row.get("rushing_yards")), _f(row.get("receiving_yards"))
    fum_total = _f(row.get("fumbles_total"))
    fum_lost = _f(row.get("fumbles_lost_total"))
    kr_td, pr_td = _f(e.get("kr_td")), _f(e.get("pr_td"))
    st = {
        "pass_yd": py, "pass_td": _f(row.get("passing_tds")), "pass_int": _f(row.get("passing_interceptions")),
        "pass_2pt": _f(row.get("passing_2pt_conversions")), "pass_td_40p": _f(e.get("pass_td_40p")),
        "bonus_pass_yd_300": 1.0 if 300 <= py < 400 else 0.0, "bonus_pass_yd_400": 1.0 if py >= 400 else 0.0,
        "rush_yd": ry, "rush_td": _f(row.get("rushing_tds")), "rush_2pt": _f(row.get("rushing_2pt_conversions")),
        "rush_td_40p": _f(e.get("rush_td_40p")),
        "bonus_rush_yd_100": 1.0 if 100 <= ry < 200 else 0.0, "bonus_rush_yd_200": 1.0 if ry >= 200 else 0.0,
        "rec": _f(row.get("receptions")), "rec_yd": cy, "rec_td": _f(row.get("receiving_tds")),
        "rec_2pt": _f(row.get("receiving_2pt_conversions")), "rec_td_40p": _f(e.get("rec_td_40p")),
        "bonus_rec_yd_100": 1.0 if 100 <= cy < 200 else 0.0, "bonus_rec_yd_200": 1.0 if cy >= 200 else 0.0,
        "bonus_rush_rec_yd_100": 1.0 if 100 <= ry + cy < 200 else 0.0, "bonus_rush_rec_yd_200": 1.0 if ry + cy >= 200 else 0.0,
        "fum": fum_total, "fum_lost": fum_lost,
        "fum_rec_td": _f(row.get("fumble_recovery_tds")),
        "kr_yd": _f(row.get("kickoff_return_yards")), "pr_yd": _f(row.get("punt_return_yards")),
        "kr_td": kr_td, "pr_td": pr_td, "st_td": kr_td + pr_td,
    }
    return st


def score(stats, scoring, exclude=()):
    """Sum stat x weight over keys present in both (same rule as engine.sleeper.league_points)."""
    total = 0.0
    for k, v in stats.items():
        if k in scoring and k not in exclude:
            total += float(v) * scoring[k]
    return round(total, 2)


def score_offense(row, extra, scoring):
    return score(offense_line(row, extra), scoring)


def score_defense(def_line, scoring):
    st = {k: v for k, v in def_line.items() if k != "opp"}
    return score(st, scoring)


def hand_check_cases():
    """Stat lines with hand-computed PSL points under this league's 88 settings (used by tests)."""
    return [
        # 300-yard passer with two TDs and an interception: 13.36 + 12 + 1 - 2 = 24.36
        ({"passing_yards": "334", "passing_tds": "2", "passing_interceptions": "1"}, {}, 24.36),
        # 412-yard passer: 16.48 + 400 bonus 2 (the 300 tier does not also pay) = 18.48
        ({"passing_yards": "412"}, {}, 18.48),
        # 410 yards, 3 TD, 2 INT, 2 fumbles 1 lost, 8 rush yds: 16.4 + 18 - 4 + 2 - 2 - 1 + 0.8 = 30.2 (Shough wk1 2026)
        ({"passing_yards": "410", "passing_tds": "3", "passing_interceptions": "2", "rushing_yards": "8",
          "fumbles_total": "2", "fumbles_lost_total": "1"}, {}, 30.2),
        # 104 rush yds, 1 TD, 1 lost fumble: 10.4 + 6 + 1 bonus - 1 fum - 1 fum_lost = 15.4
        ({"rushing_yards": "104", "rushing_tds": "1", "fumbles_total": "1", "fumbles_lost_total": "1"}, {}, 15.4),
        # 205 rush yds: 20.5 + 2 (200 tier only) = 22.5
        ({"rushing_yards": "205"}, {}, 22.5),
        # 8 catches 120 yds 1 TD (45-yard TD): 4 + 12 + 6 + 1 bonus + 1 40+ = 24.0
        ({"receptions": "8", "receiving_yards": "120", "receiving_tds": "1"}, {"rec_td_40p": 1}, 24.0),
        # 3 catches 25 yds, one fumble kept: 1.5 + 2.5 - 1 = 3.0
        ({"receptions": "3", "receiving_yards": "25", "fumbles_total": "1", "fumbles_lost_total": "0"}, {}, 3.0),
        # 2-point conversion pass plus 50-yard TD pass: 0.04*50 + 6 + 1 + 2 = 11.0
        ({"passing_yards": "50", "passing_tds": "1", "passing_2pt_conversions": "1"}, {"pass_td_40p": 1}, 11.0),
        # kick return yards and a punt return TD: 0.05*60 + 6 (pr_td) + 6 (st_td) = 15.0
        ({"kickoff_return_yards": "60"}, {"pr_td": 1}, 15.0),
        # exactly 100 receiving yards earns the bonus: 10 + 1 = 11.0
        ({"receiving_yards": "100"}, {}, 11.0),
        # 99 does not: 9.9
        ({"receiving_yards": "99"}, {}, 9.9),
    ]


def hand_check_defense_cases():
    return [
        # 3 sacks, 1 int, 1 fum rec, 1 ff, 5 tfl, 14 pts allowed, 1 three-and-out, 3 fourth-down stops, 1 blocked kick
        # = 3 + 2 + 2 + 1 + 2.5 - 1.4 + 0.5 + 3 + 3 = 15.6  (ARI week 1 2026, matches Sleeper's 15.6)
        ({"sack": 3, "int": 1, "fum_rec": 1, "ff": 1, "tkl_loss": 5, "pts_allow": 14, "def_3_and_out": 1,
          "def_4_and_stop": 3, "blk_kick": 1, "yds_allow": 268}, 15.6),
        # shutout with a pick-six and a safety: 0 + 6 + 4 + 2 (int) = 12.0
        ({"pts_allow": 0, "def_td": 1, "safe": 1, "int": 1}, 12.0),
        # 45 points allowed, nothing else: -4.5
        ({"pts_allow": 45}, -4.5),
    ]
