"""Engine-wide constants. Plain values only; no logic."""
import os

LEAGUE_ID = os.environ.get("SLEEPER_LEAGUE_ID", "1318619274968829952")
USERNAME = os.environ.get("SLEEPER_USERNAME", "Mockstar")
SEASON_HINT = "2026"
BASE = "https://api.sleeper.app"
PAGES_URL = "https://aaronbenmock.github.io/psl-sleeper-pull/"
REPO_URL = "https://github.com/aaronbenmock/psl-sleeper-pull"

FANTASY_POS = ["QB", "RB", "WR", "TE", "DEF"]
WAIVER_TOP_N = 25
TRENDING_LOOKBACK_H = 72
ENGINE_VERSION = "2.0"
PULL_VERSION = "1.2"          # the weekly pull script lineage (v1.0 -> v1.1 -> v1.2)

# Sleeper's displayed projections ignore projected return TDs; verified against the week 1 UI (v1.1)
PROJ_EXCLUDE = {"pr_td", "kr_td"}

# Stat categories this league scores that Sleeper's projections never include (known DEF bias).
DEF_UNPROJECTED_KEYS = {"def_3_and_out", "def_4_and_stop"}

DATA_DIR = "data"
REFERENCE_DIR = "reference"
REPORTS_DIR = "reports"
RANKINGS_CSV = "player_rankings_v2.0_2026-09-08.csv"
DEF_RANKINGS_CSV = "team_defense_rankings_v2.0_2026-09-08.csv"
SCHEDULE_CSV = "team_schedule_2026.csv"

# FAAB
FAAB_BUDGET_DEFAULT = 200

# Dashboard staleness: daily job means anything older than this is a failed run.
STALE_AFTER_HOURS = 26
SYNTHESIS_STALE_AFTER_DAYS = 8

# Schedule windows in America/Chicago local time. The cron fires in UTC twice (CDT and CST
# variants); the guard in timeutil.in_window() lets exactly one of them through.
# task -> list of (weekday set or None for any day, hour, minutes tolerance)
# Each task runs when the Central hour is in its list (any minute of that hour). The Wednesday
# pull accepts 10 and 11 so a late GitHub start never loses the week (a second run is harmless).
LOCAL_SCHEDULE = {
    "injuries":  {"days": None,            "hours": [6]},
    "pull":      {"days": {2},             "hours": [10, 11]},        # Wednesday
    "snapshot":  {"days": {3, 4, 5, 6, 0}, "hours": [7, 10, 18]},    # Thu, Fri, Sat, Sun, Mon
}
