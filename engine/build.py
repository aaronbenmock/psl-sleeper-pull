"""Build step: analysis + dashboard. No network. Runs at the end of every task so the live
page always reflects the most recent successful run and reports any failed one.

Writes:
  index.html                          live dashboard (GitHub Pages root)
  reports/<season>/weekNN.html        self-contained weekly archive (rewritten until the week closes)
  data/derived/*.json                 recommendation, league view, accuracy history, news zone
  PSL-Dashboard.url                   Windows shortcut to the live page
"""
import os
import traceback

from . import config, store, render
from .timeutil import now_utc, iso
from .analysis.context import Ctx
from .analysis import recommend, league_view, accuracy, news, validation, keepers, backtest


def _safe(name, fn, errors, default):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        errors.append(f"{name}: {e}")
        print(f"build: {name} failed\n{traceback.format_exc()}")
        return default


def run(data_dir=None):
    started = iso(now_utc())
    if data_dir:
        config.DATA_DIR = data_dir
    ctx = Ctx(config.DATA_DIR)
    errors = []
    empty_rec = {"week": ctx.upcoming_week, "generated_at_utc": iso(ctx.now), "source": {"kind": "none", "taken_at_utc": None},
                 "lineup": [], "bench": [], "ir": [], "current_starters": [], "changes": [], "close_calls": [],
                 "expected_total": 0, "notes": ["Lineup recommendation could not be built; see build errors."], "method": ""}
    lineup = _safe("lineup", lambda: recommend.lineup_recommendation(ctx), errors, empty_rec)
    empty_w = {"week": ctx.upcoming_week, "budget_left": 0, "budget_total": 0, "weeks_left": 0, "claims": [], "flyers": [],
               "all_evaluated": 0, "drop_candidates": [], "my_roster_values": [], "timing": "", "assumptions": []}
    waivers = _safe("waivers", lambda: recommend.waiver_recommendation(ctx, lineup), errors, empty_w)
    acc = _safe("accuracy", lambda: accuracy.build(ctx), errors,
                {"weeks": [], "pooled": {}, "fallback": None, "honesty": ["accuracy module failed"], "baselines": {"sleeper": "", "preseason": "", "naive": ""}})
    lv = _safe("league", lambda: league_view.build(ctx, lineup), errors,
               {"week_next": ctx.upcoming_week, "weeks_completed": [], "median_game": False, "league_avg": None, "teams": [], "signals": [], "notes": ["league view failed"], "projection_source": {}})
    nz = _safe("news", lambda: news.build(ctx, lineup), errors,
               {"machine": {"date_central": None, "age_hours": None, "my_roster": [], "league_changes": [], "n_tracked": 0, "source": ""},
                "synthesis": {"present": False, "markdown": "", "stale": False, "age_days": None}})
    kp = _safe("keepers", lambda: keepers.build(ctx, lineup), errors, {"week": ctx.upcoming_week, "rows": [], "top2": [], "notes": ["keeper module failed"], "rule": None})
    bt = _safe("backtest", lambda: backtest.build(ctx), errors, {"weeks": [], "verdict": "backtest failed", "table": [], "min_weeks": 4})
    checks = _safe("validation", lambda: validation.build(ctx, acc), errors, [])
    if errors:
        checks.append({"id": "build_errors", "status": "fail", "title": "Build errors", "finding": " | ".join(errors)})

    built = iso(now_utc())
    payload = {"built_at_utc": built, "completed_week": ctx.completed_week, "upcoming_week": ctx.upcoming_week,
               "lineup": lineup, "waivers": waivers, "league": lv, "accuracy_summary": {"weeks": [w["week"] for w in acc.get("weeks") or []],
               "pooled": acc.get("pooled")}, "news": nz, "validation": checks, "keepers": kp, "backtest_verdict": bt.get("verdict")}
    for name, obj in (("lineup", lineup), ("waivers", waivers), ("league_view", lv), ("news_zone", nz), ("validation", checks), ("keepers", kp)):
        store.write_json(os.path.join(config.DATA_DIR, "derived", f"{name}.json"), obj)

    season = ctx.season
    archives = []
    for f in store.list_files(os.path.join(config.REPORTS_DIR, season, "week*.html")):
        wk = int(os.path.basename(f)[4:6])
        archives.append({"week": wk, "href": f"{config.REPORTS_DIR}/{season}/week{wk:02d}.html"})
    this_href = f"{config.REPORTS_DIR}/{season}/week{ctx.upcoming_week:02d}.html"
    if not any(a["href"] == this_href for a in archives):
        archives.append({"week": ctx.upcoming_week, "href": this_href})
    archives.sort(key=lambda a: a["week"])
    # historical backtest (python engine.py histbacktest) is optional and written by a separate command
    hist = store.read_json(os.path.join(config.DATA_DIR, "derived", "hist_backtest.json"), None)
    page = {"ctx": ctx, "built_at_utc": built, "lineup": lineup, "waivers": waivers, "league": lv, "accuracy": acc,
            "news": nz, "validation": checks, "payload": payload, "archives": archives, "keepers": kp, "backtest": bt,
            "hist_backtest": hist if isinstance(hist, dict) and hist else None}
    live = render.render(page, archive=False)
    store.write_text("index.html", live)
    # archive: same data, paths relative to reports/<season>/
    page_arch = dict(page, archives=[{"week": a["week"], "href": f"week{a['week']:02d}.html"} for a in archives])
    store.write_text(os.path.join(config.REPORTS_DIR, season, f"week{ctx.upcoming_week:02d}.html"), render.render(page_arch, archive=True))
    store.write_text("PSL-Dashboard.url", f"[InternetShortcut]\r\nURL={config.PAGES_URL}\r\n")
    store.write_text(".nojekyll", "")
    summary = (f"index.html + {this_href}; lineup changes {len(lineup['changes'])}, claims {len(waivers['claims'])}, "
               f"signals {len(lv['signals'])}, accuracy weeks {len(acc.get('weeks') or [])}" + (f"; ERRORS: {errors}" if errors else ""))
    store.record_run("build", not errors, summary, started, built, error="; ".join(errors) if errors else None)
    print("build:", summary)
    if errors:
        raise RuntimeError("build completed with section errors: " + "; ".join(errors))
    return page
