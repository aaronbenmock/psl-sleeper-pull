"""Optional news synthesis inside the Action, via the Anthropic Messages API with web search.

Runs only when the ANTHROPIC_API_KEY secret is set on the repo (otherwise it records "skipped"
and the dashboard's synthesis box stays empty). Stdlib only: raw HTTP to api.anthropic.com.
This is path B for requirement 11. Path A is the weekly scheduled Claude task on Aaron's
desktop app, which writes the same file (data/synthesis/latest.md) and pushes it.

Cost: one call per week with up to 8 web searches. Roughly a few cents to a few tens of
cents per run on claude-opus-5 [Likely].
"""
import json
import os
import urllib.error
import urllib.request

from . import config, store
from .timeutil import now_utc, iso, to_central

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("SYNTHESIS_MODEL", "claude-opus-5")

SYSTEM = """You are the weekly news analyst for one fantasy football manager (Aaron, Sleeper league
"Pretend Sportsball League '26", half-PPR, 2 FLEX, no TE slot, no kicker, team defense scored with
sacks, TFLs, 3-and-outs and 4th-down stops). You will be given machine data from Sleeper (his roster,
injury fields, the waiver targets an engine already picked) and you do a news pass with web search.

Write the "top things to know" section for his dashboard. Rules:
- Plain English, no em dashes, no code. Short bullets. Lead with what changes a decision.
- Every claim that comes from the web must name the source and the date in the bullet.
- Tag anything not confirmed by a source [Likely] or [Guessing]. Never present a rumor as fact.
- Do not repeat the machine data back; add what Sleeper's fields cannot say (why, how long, who benefits).
- Sections, in this order, each a markdown ## heading:
  ## Your roster: what changed this week
  ## Waiver targets: news check
  ## League: notable situations
  ## Bottom line (3 bullets max)
- Under 600 words."""


def _post(payload, key, timeout=600):
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json",
                                          "user-agent": f"psl-engine/{config.ENGINE_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def build_context(data_dir):
    lineup = store.read_json(os.path.join(data_dir, "derived", "lineup.json"), {}) or {}
    waivers = store.read_json(os.path.join(data_dir, "derived", "waivers.json"), {}) or {}
    nz = store.read_json(os.path.join(data_dir, "derived", "news_zone.json"), {}) or {}
    lv = store.read_json(os.path.join(data_dir, "derived", "league_view.json"), {}) or {}
    roster = [{k: r.get(k) for k in ("name", "pos", "team", "slot", "opp", "sleeper", "expected", "injury_status", "injury_body_part", "practice")}
              for r in (lineup.get("lineup") or []) + (lineup.get("bench") or []) + (lineup.get("ir") or [])]
    inj = [{k: r.get(k) for k in ("name", "pos", "team", "injury_status", "injury_body_part", "practice_participation",
                                  "practice_description", "injury_notes", "news_updated", "history")}
           for r in (nz.get("machine") or {}).get("my_roster") or [] if r.get("injury_status") or r.get("history")]
    claims = [{k: c.get(k) for k in ("name", "pos", "team", "next_proj", "ros", "gain", "bid", "trending", "injury_status")}
              for c in (waivers.get("claims") or [])[:6]]
    signals = [s.get("text") for s in (lv.get("signals") or [])[:8]]
    return {"week": lineup.get("week"), "roster": roster, "injury_flags": inj, "waiver_targets": claims, "league_signals": signals}


def run(out_dir=None):
    data_dir = out_dir or config.DATA_DIR
    started = iso(now_utc())
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        store.record_run("synthesis", True, "skipped: ANTHROPIC_API_KEY not set (path B not enabled)", started, iso(now_utc()))
        print("synthesis: skipped, no ANTHROPIC_API_KEY")
        return None
    ctx = build_context(data_dir)
    week = ctx.get("week")
    user_msg = (f"Today is {to_central(now_utc()).strftime('%A %B %d, %Y')} Central. Upcoming NFL week: {week}.\n\n"
                f"MACHINE DATA (from Sleeper, via the engine):\n{json.dumps(ctx, indent=1)}\n\n"
                "Do the news pass now and write the section.")
    messages = [{"role": "user", "content": user_msg}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}]
    text_parts, searches = [], 0
    for _ in range(4):
        payload = {"model": MODEL, "max_tokens": 8000, "system": SYSTEM, "messages": messages, "tools": tools}
        try:
            resp = _post(payload, key)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"Anthropic API HTTP {e.code}: {body}")
        content = resp.get("content") or []
        for block in content:
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "server_tool_use":
                searches += 1
        stop = resp.get("stop_reason")
        if stop == "pause_turn":
            messages.append({"role": "assistant", "content": content})
            continue
        if stop == "refusal":
            raise RuntimeError(f"model refused: {resp.get('stop_details')}")
        break
    md = "\n".join(t.strip() for t in text_parts if t.strip()).strip()
    if not md:
        raise RuntimeError("empty synthesis text")
    now = now_utc()
    header = (f"<!-- generated {iso(now)} by engine synthesis (Anthropic API, {MODEL}, {searches} web searches) -->\n")
    store.write_text(os.path.join(data_dir, "synthesis", "latest.md"), header + md + "\n")
    store.write_text(os.path.join(data_dir, "synthesis", f"week{int(week or 0):02d}_synthesis_{now:%Y-%m-%d}.md"), header + md + "\n")
    store.write_json(os.path.join(data_dir, "synthesis", "latest.json"),
                     {"generated_at_utc": iso(now), "week": week, "source": f"Anthropic API ({MODEL}) inside GitHub Actions",
                      "web_searches": searches, "usage": resp.get("usage")})
    summary = f"week {week}: {len(md.split())} words, {searches} web searches, model {MODEL}"
    store.record_run("synthesis", True, summary, started, iso(now_utc()))
    print("synthesis:", summary)
    return md
