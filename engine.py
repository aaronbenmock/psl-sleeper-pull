#!/usr/bin/env python3
"""PSL Weekly Fantasy Engine, single entry point (stdlib only).

  python engine.py pull        Wednesday weekly pull (v1.2), then build
  python engine.py injuries    daily injury tracker, then build
  python engine.py snapshot    pre-kickoff projection snapshot, then build
  python engine.py build       analysis + dashboard only, no network
  python engine.py auto        decide from the current Central time which task the cron meant
  python engine.py synthesis   optional news synthesis via the Anthropic API (needs ANTHROPIC_API_KEY)
  python engine.py full        pull + injuries + snapshot + build (first run after a push)
  python engine.py backtest    same as build (the backtest runs inside every build); prints its verdict

Every task ends with `build`, so the dashboard always reflects the latest successful run and
records the failure of any task in data/status.json (the dashboard shows it).
"""
import argparse
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import config, store  # noqa: E402
from engine.timeutil import now_utc, now_central, iso, in_window, self_test  # noqa: E402


def _run_task(name, fn, **kw):
    started = iso(now_utc())
    try:
        fn(**kw)
        return True
    except SystemExit as e:
        store.record_run(name, False, f"stopped: {e}", started, iso(now_utc()), error=str(e))
        print(f"{name}: stopped: {e}")
        return False
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        store.record_run(name, False, f"failed: {e}", started, iso(now_utc()), error=tb[-2000:])
        print(f"{name}: FAILED\n{tb}")
        return False


def task_pull(args):
    from engine import pull
    return _run_task("pull", pull.run, completed_override=args.completed_week)


def task_injuries(args):
    from engine import injuries
    return _run_task("injuries", injuries.run)


def task_snapshot(args):
    from engine import snapshot
    return _run_task("snapshot", snapshot.run, week_override=args.week)


def task_synthesis(args):
    from engine import synthesis
    return _run_task("synthesis", synthesis.run)


def task_build(args):
    from engine import build
    return _run_task("build", build.run)


def decide_auto():
    """Map the current Central time onto the intended task. Returns list of task names."""
    local = now_central()
    tasks = []
    s = config.LOCAL_SCHEDULE
    if in_window(local, s["injuries"]["hours"], s["injuries"]["days"]):
        tasks.append("injuries")
    if in_window(local, s["pull"]["hours"], s["pull"]["days"]):
        tasks.append("pull")
    if in_window(local, s["snapshot"]["hours"], s["snapshot"]["days"]):
        tasks.append("snapshot")
    return local, tasks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["pull", "injuries", "snapshot", "build", "auto", "synthesis", "full", "selftest", "backtest"])
    ap.add_argument("--completed-week", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--no-build", action="store_true")
    args = ap.parse_args()

    if args.task == "selftest":
        print("timeutil:", self_test())
        local, tasks = decide_auto()
        print(f"now central {local.isoformat()} -> auto would run {tasks or 'nothing (outside every window)'}")
        return

    ok = True
    if args.task == "auto":
        local, tasks = decide_auto()
        print(f"auto: central time {local.isoformat()} -> tasks {tasks}")
        if not tasks:
            print("auto: fired outside every scheduled window (this is the duplicate DST cron, or GitHub was very late). "
                  "Skipping data pulls; still rebuilding the dashboard so its data age stays honest.")
            store.record_run("auto-skip", True, f"skipped at {local.isoformat()}", iso(now_utc()), iso(now_utc()))
        for t in tasks:
            ok = {"injuries": task_injuries, "pull": task_pull, "snapshot": task_snapshot}[t](args) and ok
        if "pull" in tasks and os.environ.get("ANTHROPIC_API_KEY"):
            task_build(args)          # synthesis reads the derived files, so build first
            ok = task_synthesis(args) and ok
    elif args.task == "full":
        ok = task_pull(args)
        ok = task_injuries(args) and ok
        ok = task_snapshot(args) and ok
    elif args.task == "pull":
        ok = task_pull(args)
    elif args.task == "injuries":
        ok = task_injuries(args)
    elif args.task == "snapshot":
        ok = task_snapshot(args)
    elif args.task == "synthesis":
        ok = task_synthesis(args)

    if not args.no_build:
        built = task_build(args)
        ok = ok and built
    if args.task == "backtest":
        print(open(os.path.join(config.DATA_DIR, "derived", "backtest.md"), encoding="utf-8").read())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
