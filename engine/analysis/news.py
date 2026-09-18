"""News and injury zone. Two clearly separated halves:
  machine   Sleeper's injury/practice fields for Aaron's roster, with day-over-day changes
            (fully automated, no news source, zero cost).
  synthesis the weekly Claude news pass, read from data/synthesis/latest.md if present,
            with its own date and a stale flag. Never mixed with the machine half.
"""
import datetime as dt

from .. import config
from ..timeutil import parse_iso


def _ms_to_date(ms):
    if not ms:
        return None
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        return None


def build(ctx, lineup_rec):
    table = (ctx.injuries or {}).get("players") or {}
    my_rows = []
    order = {"IR": 3, "BN": 2}
    roster_ids = [r.get("player_id") for r in lineup_rec["lineup"] + lineup_rec["bench"] + lineup_rec["ir"] if r.get("player_id")]
    slot_of = {r["player_id"]: r["slot"] for r in lineup_rec["lineup"] + lineup_rec["bench"] + lineup_rec["ir"] if r.get("player_id")}
    recent = []
    for d in ctx.injury_diffs[-7:]:
        for c in d.get("changes") or []:
            recent.append(dict(c, date=d.get("date_central")))
    for pid in roster_ids:
        row = table.get(pid) or {}
        p = ctx.players.get(pid) or ctx.fallback_players.get(pid) or {}
        info = ctx.info(pid)
        changes = [c for c in recent if c.get("player_id") == pid]
        hist = []
        for c in changes:
            for f, v in (c.get("fields") or {}).items():
                hist.append(f"{c['date']}: {f.replace('_', ' ')} {v.get('from') or 'none'} to {v.get('to') or 'none'}")
        my_rows.append({
            "player_id": pid, "name": info["name"], "pos": info["pos"], "team": info["team"], "slot": slot_of.get(pid, "BN"),
            "injury_status": row.get("injury_status") or p.get("injury_status"),
            "injury_body_part": row.get("injury_body_part") or p.get("injury_body_part"),
            "injury_start_date": row.get("injury_start_date") or p.get("injury_start_date"),
            "injury_notes": row.get("injury_notes") or p.get("injury_notes"),
            "practice_participation": row.get("practice_participation") or p.get("practice_participation"),
            "practice_description": row.get("practice_description") or p.get("practice_description"),
            "news_updated": _ms_to_date(row.get("news_updated") or p.get("news_updated")),
            "depth_chart_order": row.get("depth_chart_order") if row.get("depth_chart_order") is not None else p.get("depth_chart_order"),
            "history": hist[-6:],
        })
    my_rows.sort(key=lambda r: (0 if r["injury_status"] else 1, order.get(r["slot"], 1), r["name"]))
    league_changes = [c for c in recent if not c.get("is_mine")]
    league_changes.sort(key=lambda c: (c.get("date") or "", c.get("team_name") or ""), reverse=True)
    league_changes = league_changes[:25]
    inj_date = (ctx.injuries or {}).get("date_central")
    inj_pulled = parse_iso((ctx.injuries or {}).get("pulled_at_utc"))
    inj_age_h = round((ctx.now - inj_pulled).total_seconds() / 3600, 1) if inj_pulled else None

    # synthesis half
    synth = {"present": bool(ctx.synthesis_md.strip()), "markdown": ctx.synthesis_md,
             "generated_at_utc": ctx.synthesis_meta.get("generated_at_utc"), "week": ctx.synthesis_meta.get("week"),
             "source": ctx.synthesis_meta.get("source"), "stale": False, "age_days": None}
    t = parse_iso(synth["generated_at_utc"])
    if t:
        synth["age_days"] = round((ctx.now - t).total_seconds() / 86400, 1)
        synth["stale"] = synth["age_days"] > config.SYNTHESIS_STALE_AFTER_DAYS
    return {"machine": {"date_central": inj_date, "age_hours": inj_age_h, "my_roster": my_rows,
                        "league_changes": league_changes, "n_tracked": len(table),
                        "source": "Sleeper /v1/players/nfl injury fields, pulled once daily, diffed against the prior day"},
            "synthesis": synth}
