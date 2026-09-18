"""Loads everything the analysis layer needs from the committed data tree. Every input is
optional: the build must succeed on day one with only the genuine v1.1 latest.json present,
and it must keep succeeding if any single collector fails."""
import os
import statistics

from .. import config, store, reference
from ..sleeper import load_cached_players_only, player_info
from ..timeutil import now_utc, parse_iso


class Ctx:
    def __init__(self, data_dir=None):
        d = self.data_dir = data_dir or config.DATA_DIR
        self.now = now_utc()
        self.latest = store.read_json(os.path.join(d, "latest.json"), {}) or {}
        self.meta = self.latest.get("meta") or {}
        self.season = str(self.meta.get("season") or config.SEASON_HINT)
        self.completed_week = int(self.meta.get("completed_week") or 0)
        self.upcoming_week = int(self.meta.get("upcoming_week") or (self.completed_week + 1))
        self.league = store.read_json(os.path.join(d, "league", "league.json"), {}) or {}
        self.settings = self.league.get("settings") or {}
        self.scoring = {k: float(v) for k, v in (self.league.get("scoring_settings") or {}).items()}
        self.slots = [p for p in (self.league.get("roster_positions") or
                                  ["QB", "RB", "RB", "WR", "WR", "FLEX", "FLEX", "DEF"]) if p not in ("BN", "IR")]
        rj = store.read_json(os.path.join(d, "league", "rosters.json"), {}) or {}
        self.rosters = rj.get("rosters") or []
        self.rosters_pulled = parse_iso(rj.get("pulled_at_utc"))
        self.users = store.read_json(os.path.join(d, "league", "users.json"), []) or []
        self.user_by_id = {u.get("user_id"): u for u in self.users}
        self.players, self.players_meta = load_cached_players_only(d)
        # day-one fallback: before the first daily players pull, the only player info is in latest.json
        self.fallback_players = {}
        lt = self.latest
        rows = []
        for blk in ("completed_week", "upcoming_week"):
            b = lt.get(blk) or {}
            rows += (b.get("starters") or []) + (b.get("bench") or []) + (b.get("ir") or [])
        for pos_rows in (lt.get("waivers_by_position") or {}).values():
            rows += pos_rows
        rows += lt.get("waivers_trending") or []
        for r in rows:
            pid = r.get("player_id")
            if pid and r.get("name") != "EMPTY" and pid not in self.players:
                self.fallback_players[pid] = {"player_id": pid, "full_name": r.get("name"), "position": r.get("pos"),
                                              "team": r.get("team"), "injury_status": r.get("injury_status"),
                                              "injury_body_part": r.get("injury_body_part"),
                                              "depth_chart_order": r.get("depth_chart_order"), "status": r.get("bye_or_status")}
        self.status = store.load_status()
        self.matchups = {}
        for f in store.list_files(os.path.join(d, "league", "matchups", "week*.json")):
            wk = int(os.path.basename(f)[4:6])
            self.matchups[wk] = store.read_json(f, []) or []
        self.scored = {}
        for f in store.list_files(os.path.join(d, "weeks", self.season, "week*_scored.json")):
            wk = int(os.path.basename(f)[4:6])
            self.scored[wk] = store.read_json(f, {}) or {}
        self.snap_index = (store.read_json(os.path.join(d, "snapshots", self.season, "index.json"), {}) or {}).get("snapshots") or []
        inj_files = store.list_files(os.path.join(d, "injuries", self.season, "injuries_*.json"))
        self.injuries = store.read_json(inj_files[-1], {}) if inj_files else {}
        self.injury_history = [store.read_json(f, {}) for f in inj_files[-8:]]
        diff_files = store.list_files(os.path.join(d, "injuries", self.season, "diff_*.json"))
        self.injury_diffs = [store.read_json(f, {}) for f in diff_files[-7:]]
        self.transactions = (store.read_json(os.path.join(d, "league", "transactions.json"), {}) or {}).get("by_week") or {}
        self.synthesis_md = store.read_text(os.path.join(d, "synthesis", "latest.md"), "")
        self.synthesis_meta = store.read_json(os.path.join(d, "synthesis", "latest.json"), {}) or {}
        self.my_rid = self._find_my_rid()
        self.my_roster = next((r for r in self.rosters if r.get("roster_id") == self.my_rid), None)
        self.rankings = reference.rankings()
        self.def_rankings = reference.def_rankings()
        self.schedule = reference.schedule()

    # ---- helpers
    def _find_my_rid(self):
        u = config.USERNAME.lower()
        me = next((x for x in self.users if (x.get("display_name") or "").lower() == u), None)
        if me:
            r = next((r for r in self.rosters if r.get("owner_id") == me.get("user_id")), None)
            if r:
                return r["roster_id"]
        # fall back to the scoreboard row that matches the genuine pull's my_team name
        my_team = (self.latest.get("completed_week") or {}).get("my_team")
        for row in (self.latest.get("completed_week") or {}).get("league_scoreboard") or []:
            if row.get("team") == my_team:
                return row.get("roster_id")
        return None

    def team_name(self, rid):
        r = next((x for x in self.rosters if x.get("roster_id") == rid), {})
        u = self.user_by_id.get(r.get("owner_id"), {})
        name = u.get("team_name") or u.get("display_name")
        if name:
            return name
        for row in (self.latest.get("completed_week") or {}).get("league_scoreboard") or []:
            if row.get("roster_id") == rid:
                return row.get("team")
        return f"roster {rid}"

    def manager_name(self, rid):
        r = next((x for x in self.rosters if x.get("roster_id") == rid), {})
        u = self.user_by_id.get(r.get("owner_id"), {})
        return u.get("display_name") or ""

    def info(self, pid):
        if pid in self.players or pid not in self.fallback_players:
            return player_info(pid, self.players)
        return player_info(pid, self.fallback_players)

    def name(self, pid):
        return self.info(pid)["name"]

    def injury(self, pid):
        """Latest injury fields for a player: from today's injury table, else the players cache."""
        row = ((self.injuries or {}).get("players") or {}).get(pid)
        if row:
            return row
        p = self.players.get(pid) or self.fallback_players.get(pid) or {}
        return {k: p.get(k) for k in ("injury_status", "injury_body_part", "practice_participation",
                                      "practice_description", "injury_notes", "news_updated", "depth_chart_order")}

    def preseason(self, pid, pos=None, team=None):
        info = self.info(pid)
        return reference.preseason_row(pid, pos or info["pos"], team or info["team"])

    def preseason_ppg(self, pid, pos=None, team=None):
        r = self.preseason(pid, pos, team)
        if not r:
            return None
        return r.get("proj_ppg") if (pos or self.info(pid)["pos"]) != "DEF" else r.get("wtd_def_ppg")

    def actuals(self, pid):
        """List of (week, actual points) for completed weeks, from the scored files."""
        out = []
        for wk in sorted(self.scored):
            row = (self.scored[wk].get("players") or {}).get(pid)
            if row and row.get("actual") is not None:
                out.append((wk, row["actual"]))
        return out

    def season_avg(self, pid, before_week=None):
        pts = [a for wk, a in self.actuals(pid) if before_week is None or wk < before_week]
        return (round(statistics.mean(pts), 2), len(pts)) if pts else (None, 0)

    def data_age_hours(self):
        t = parse_iso(self.meta.get("pulled_at_utc"))
        return round((self.now - t).total_seconds() / 3600, 1) if t else None

    def last_success(self, task):
        rec = (self.status.get("tasks") or {}).get(task)
        return rec if rec and rec.get("ok") else None

    def bye_week(self, team):
        return reference.bye_week(team)

    def opponent(self, team, week):
        s = self.schedule.get((team, week))
        return s.get("opponent") if s else None
