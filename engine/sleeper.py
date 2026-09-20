"""Sleeper HTTP client (stdlib only), league scoring, and the once-per-day players cache.

Fixture mode: set SLEEPER_FIXTURE_DIR to a folder of saved responses and every GET reads
from a file instead of the network. Used for local testing because api.sleeper.app is
unreachable from Claude's environments.
"""
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.request

from . import config
from .timeutil import now_utc, iso, parse_iso, eastern_date

FIXTURE_DIR = os.environ.get("SLEEPER_FIXTURE_DIR")
_CALLS = []


def _fixture_name(url):
    path = url.replace(config.BASE, "")
    path = path.replace("season_type=regular&" + "&".join(f"position[]={p}" for p in config.FANTASY_POS), "all")
    return re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_")[:120] + ".json"


def get(path, retries=4, timeout=60):
    url = path if path.startswith("http") else config.BASE + path
    _CALLS.append(url)
    if FIXTURE_DIR:
        fp = os.path.join(FIXTURE_DIR, _fixture_name(url))
        if not os.path.exists(fp):
            raise RuntimeError(f"fixture missing for {url}: {fp}")
        with open(fp, encoding="utf-8") as f:
            return json.load(f)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"psl-engine/{config.ENGINE_VERSION}"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET {url} failed after {retries} tries: {last}")


def calls_made():
    return list(_CALLS)


# ---------------------------------------------------------------- scoring
def league_points(stats, scoring, exclude=()):
    """Sum stat * scoring weight for every key present in both. None if no stats."""
    if not stats:
        return None
    total = 0.0
    for k, v in stats.items():
        if k in scoring and k not in exclude and isinstance(v, (int, float)):
            total += float(v) * scoring[k]
    return round(total, 2)


def points_by_category(stats, scoring, keys):
    """Points contributed by a subset of stat keys (isolates the unprojected DEF stats)."""
    if not stats:
        return 0.0
    return round(sum(float(stats.get(k) or 0) * scoring.get(k, 0.0) for k in keys), 2)


def stat_map(rows):
    out = {}
    for row in rows or []:
        pid = row.get("player_id")
        if pid:
            out[str(pid)] = row
    return out


def pull_position_rows(kind, season, week):
    """kind = 'projections' or 'stats'. Every fantasy position in one call."""
    qs = "&".join(f"position[]={p}" for p in config.FANTASY_POS)
    return stat_map(get(f"/{kind}/nfl/{season}/{week}?season_type=regular&{qs}"))


# ---------------------------------------------------------------- players cache
SLIM_FIELDS = ["first_name", "last_name", "full_name", "position", "fantasy_positions", "team", "status",
               "active", "injury_status", "injury_body_part", "injury_start_date", "injury_notes",
               "practice_participation", "practice_description", "news_updated", "depth_chart_order",
               "depth_chart_position", "years_exp", "age", "search_rank", "number", "gsis_id"]


def slim_players(players, keep_ids=()):
    """Keep fantasy-relevant players only, with the fields the engine uses."""
    keep_ids = set(keep_ids)
    out = {}
    for pid, p in players.items():
        if not isinstance(p, dict):
            continue
        pos = p.get("position")
        relevant = (pos in config.FANTASY_POS and (p.get("team") or pid in keep_ids)) or pid in keep_ids
        if not relevant:
            continue
        out[pid] = {k: p.get(k) for k in SLIM_FIELDS if p.get(k) is not None}
        out[pid]["player_id"] = pid
    return out


def players_cache_path(data_dir=None):
    return os.path.join(data_dir or config.DATA_DIR, "players", "players_slim.json")


def load_players(data_dir=None, keep_ids=(), max_age_hours=20, force=False):
    """Return (players_slim, meta). Pulls /players/nfl at most once per day by reusing the
    committed slim cache while it is fresh. Sleeper asks for <= 1 full pull per day."""
    path = players_cache_path(data_dir)
    if os.path.exists(path) and not force:
        with open(path, encoding="utf-8") as f:
            cached = json.load(f)
        pulled = parse_iso((cached.get("meta") or {}).get("pulled_at_utc"))
        if pulled and (now_utc() - pulled).total_seconds() < max_age_hours * 3600:
            return cached["players"], dict(cached["meta"], reused=True)
    raw = get("/v1/players/nfl")
    slim = slim_players(raw, keep_ids)
    meta = {"pulled_at_utc": iso(now_utc()), "raw_count": len(raw), "slim_count": len(slim), "reused": False}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "players": slim}, f, separators=(",", ":"), sort_keys=True)
    return slim, meta


def load_cached_players_only(data_dir=None):
    """Read the slim cache without any network call. Empty dict if it does not exist yet."""
    path = players_cache_path(data_dir)
    if not os.path.exists(path):
        return {}, {}
    with open(path, encoding="utf-8") as f:
        cached = json.load(f)
    return cached.get("players") or {}, cached.get("meta") or {}


def player_info(pid, players):
    p = players.get(pid) or {}
    if p.get("position") == "DEF" or (not p and pid.isalpha()):
        return {"player_id": pid, "name": f"{pid} DEF", "pos": "DEF", "team": pid,
                "injury_status": None, "depth_chart_order": None}
    name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or pid
    return {
        "player_id": pid,
        "name": name,
        "pos": p.get("position"),
        "team": p.get("team"),
        "injury_status": p.get("injury_status"),
        "injury_body_part": p.get("injury_body_part"),
        "depth_chart_order": p.get("depth_chart_order"),
        "bye_or_status": p.get("status"),
    }


# ---------------------------------------------------------------- league basics
def load_league_basics():
    state = get("/v1/state/nfl")
    league = get(f"/v1/league/{config.LEAGUE_ID}")
    users = get(f"/v1/league/{config.LEAGUE_ID}/users")
    rosters = get(f"/v1/league/{config.LEAGUE_ID}/rosters")
    return state, league, users, rosters


def find_me(users):
    u = config.USERNAME.lower()
    return next((x for x in users if (x.get("display_name") or "").lower() == u
                 or (x.get("username") or "").lower() == u), None)


def team_name_fn(users, rosters):
    user_by_id = {u["user_id"]: u for u in users}

    def name(roster_id):
        r = next((x for x in rosters if x["roster_id"] == roster_id), {})
        u = user_by_id.get(r.get("owner_id"), {})
        return (u.get("metadata") or {}).get("team_name") or u.get("display_name") or f"roster {roster_id}"
    return name


def week_game_dates(proj_rows):
    """Sorted game dates (YYYY-MM-DD) present in a week's projection rows."""
    return sorted({r.get("date") for r in proj_rows.values() if r.get("date")})


def detect_weeks(state, season, now=None, proj_cache=None):
    """Return (completed_week, upcoming_week, how).

    A week is complete when the latest game date among its projection rows is before today
    (US Eastern). This is robust on every weekday, unlike 'matchups have points', which flips
    as soon as the Thursday game starts. proj_cache (dict) receives the projection rows pulled
    along the way so callers do not pull them twice.
    """
    now = now or now_utc()
    today = eastern_date(now)
    w = int(state.get("week") or 0)
    if w < 1:
        return 0, 1, "preseason"
    cand = w
    how = "projection game dates"
    for _ in range(3):
        rows = pull_position_rows("projections", season, cand)
        if proj_cache is not None:
            proj_cache[cand] = rows
        dates = week_game_dates(rows)
        if not dates:
            m = get(f"/v1/league/{config.LEAGUE_ID}/matchups/{cand}")
            has_points = any((x.get("points") or 0) != 0 for x in m)
            how = "v1.1 fallback (matchup points)"
            if has_points:
                return cand, cand + 1, how
            cand -= 1
            if cand < 1:
                return 0, 1, how
            continue
        last_game = dt.date.fromisoformat(max(dates))
        if last_game < today:
            return cand, cand + 1, how
        cand -= 1
        if cand < 1:
            return 0, 1, how
    return max(cand, 0), max(cand, 0) + 1, how
