#!/usr/bin/env python3
"""One-off: reconstruct the calls files for weeks 2 to 4 (data/derived/calls/<season>/weekNN.json)
from git history, so the Accuracy tab's calls scorecard has something to grade before the live
recording (engine/analysis/calls.py) has run for a full week.

For each week it takes the last committed data/derived/lineup.json before that week's first kickoff
(week 2 has none: the engine was first built the day after week 2's Thursday game, so its first
build is used and the grader skips the Thursday players) and the last data/derived/waivers.json
before the Thursday 2:00 AM Central waiver run. The synthesis calls were extracted by hand from the
week markdown files in data/synthesis/ on 2026-09-30 and are written with source "extracted by hand".

Also seeds data/players/names_cache.json from every committed version of players_slim.json.

  python tools/backfill_calls.py           writes the files (never overwrites a live-recorded week)
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from engine import store  # noqa: E402
from engine.analysis import calls as cl  # noqa: E402
from engine.sleeper import player_info, names_cache_path  # noqa: E402
from engine.timeutil import parse_iso, iso, now_utc  # noqa: E402

SEASON = "2026"
# week -> (first kickoff UTC, waiver run UTC); rec commits are the last ones before these
WEEKS = {
    2: ("2026-09-18T00:15:00Z", "2026-09-17T07:00:00Z"),
    3: ("2026-09-25T00:15:00Z", "2026-09-24T07:00:00Z"),
    4: ("2026-10-02T00:15:00Z", "2026-10-01T07:00:00Z"),
}

# Hand-extracted from data/synthesis/weekNN_synthesis_*.md (bottom lines and explicit bid / start advice).
SYNTH = {
    2: {"file": "week02_synthesis_2026-09-18.md", "made_at_utc": "2026-09-18T17:23:12Z", "calls": [
        {"type": "claim", "name": "Dallas Goedert", "bid": 25, "text": "Bid $25 on Goedert (would start at flex)"},
        {"type": "claim", "name": "Devin Singletary", "bid": 11, "text": "Consider $11 on Singletary only as depth"},
    ]},
    3: {"file": "week03_synthesis_2026-09-23.md", "made_at_utc": "2026-09-23T17:15:00Z", "calls": [
        {"type": "start", "name": "Woody Marks", "alt_name": "George Holani", "text": "If Dowdle is out, plug in Woody Marks, not George Holani"},
        {"type": "claim", "name": "Travis Kelce", "bid": 22, "text": "Put your FAAB weight behind Travis Kelce at $22"},
    ]},
    4: {"file": "week04_synthesis_2026-09-30.md", "made_at_utc": "2026-09-30T21:26:11Z", "calls": [
        {"type": "start", "name": "Josh Allen", "alt_name": "Kyler Murray", "text": "Start Allen"},
        {"type": "start", "name": "Denzel Boston", "alt_name": "DK Metcalf", "text": "Lock the Boston over Metcalf call before Thursday night"},
        {"type": "claim", "name": "Harold Fannin", "bid": 10, "text": "Put in Fannin ($10)"},
        {"type": "claim", "name": "Kenyon Sadiq", "bid": 11, "text": "A Sadiq bid at the engine's $11 only"},
        {"type": "skip", "name": "LV DEF", "alt_name": "SEA DEF", "text": "Skip the LV defense swap this week"},
    ]},
}


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True, encoding="utf-8").stdout


def last_before(path, until):
    out = git("log", "-1", "--format=%H %aI", f"--until={until}", "--", path).strip()
    return out.split() if out else (None, None)


def first_commit(path):
    out = git("log", "--reverse", "--format=%H %aI", "--", path).strip().splitlines()
    return out[0].split() if out else (None, None)


def show(sha, path):
    return json.loads(git("show", f"{sha}:{path}"))


def seed_names_cache():
    cache = {}
    shas = git("log", "--format=%H %aI", "--", "data/players/players_slim.json").strip().splitlines()
    for line in reversed(shas):           # oldest first, so newer names win
        sha, when = line.split()
        try:
            players = show(sha, "data/players/players_slim.json").get("players") or {}
        except (subprocess.CalledProcessError, ValueError):
            continue
        day = when[:10]
        for pid, p in players.items():
            info = player_info(pid, players)
            old = cache.get(pid) or {}
            cache[pid] = {"name": info["name"], "pos": info["pos"], "team": info["team"] or old.get("team"),
                          "first_seen": old.get("first_seen") or day, "last_seen": day}
    path = names_cache_path("data")
    cur = (store.read_json(path, {}) or {}).get("players") or {}
    cur.update({k: v for k, v in cache.items() if k not in cur})
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated_utc": iso(now_utc()), "n": len(cur), "players": cur}, f, indent=0, sort_keys=True)
    print(f"names cache: {len(cur)} players from {len(shas)} versions of players_slim.json")
    return cur


def resolve(name, names):
    if name.endswith(" DEF"):
        return name.split()[0]
    hits = [pid for pid, v in names.items() if v.get("name") == name]
    return hits[0] if hits else None


def main():
    names = seed_names_cache()
    for week, (kick, run) in WEEKS.items():
        path = cl.calls_path("data", SEASON, week)
        existing = store.read_json(path, {}) or {}
        if existing and existing.get("source") == "live build":
            print(f"week {week}: live-recorded file exists, left alone")
            continue
        sha, when = last_before("data/derived/lineup.json", kick)
        note = "last build before the week's first kickoff"
        lineup = show(sha, "data/derived/lineup.json") if sha else {}
        if not sha or int(lineup.get("week") or 0) != week:
            sha, when = first_commit("data/derived/lineup.json")
            lineup = show(sha, "data/derived/lineup.json")
            note = "first build of the engine, made after the week's Thursday game"
        if int(lineup.get("week") or 0) != week:
            print(f"week {week}: no lineup recommendation for this week in history, skipped")
            continue
        wsha, wwhen = last_before("data/derived/waivers.json", run)
        waivers = show(wsha, "data/derived/waivers.json") if wsha else {}
        if int(waivers.get("week") or 0) != week:
            wsha, wwhen = sha, when
            waivers = show(wsha, "data/derived/waivers.json")
        s = SYNTH.get(week) or {}
        syn = []
        for c in s.get("calls") or []:
            c = dict(c, player_id=resolve(c["name"], names), source="extracted by hand", made_at_utc=s["made_at_utc"],
                     file=s["file"])
            if c.get("alt_name"):
                c["alt_id"] = resolve(c["alt_name"], names)
            syn.append(c)
        rec_t = parse_iso(when)
        out = cl.merge({}, week, rec_t, lineup, waivers, None, rec_source=f"backfilled from git {sha[:7]} ({note})")
        out["first_recorded_utc"] = iso(rec_t)
        out["claims_rec_utc"] = iso(parse_iso(wwhen))
        out["claims_source"] = f"git {wsha[:7]}"
        out["claims_frozen"] = True
        out["synthesis"] = syn
        for c in out["start_sit"]:
            c["frozen"] = True
        for r in out["lineup"]:
            r["frozen"] = True
        if week == 4:
            # the live build keeps recording week 4 until Thursday; only seed it
            out["source"] = "live build"
            out["claims_frozen"] = False
            for c in out["start_sit"]:
                c["frozen"] = bool(c.get("started"))
            for r in out["lineup"]:
                r["frozen"] = bool(r.get("started"))
        store.write_json(path, out)
        print(f"week {week}: lineup {sha[:7]} {when}, waivers {wsha[:7]} {wwhen}, {len(out['start_sit'])} start/sit, "
              f"{len(out['claims'])} claims, {len(syn)} synthesis calls")


if __name__ == "__main__":
    main()
