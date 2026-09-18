"""Small helpers for reading and writing the committed data tree."""
import glob
import json
import os

from . import config


def p(*parts):
    return os.path.join(config.DATA_DIR, *parts)


def read_json(path, default=None):
    if not path or not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj, compact=False):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, separators=(",", ":"), sort_keys=True)
        else:
            json.dump(obj, f, indent=1)
    return path


def write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def read_text(path, default=""):
    if not path or not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return f.read()


def latest_file(pattern):
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def list_files(pattern):
    return sorted(glob.glob(pattern))


# ---- status.json: one record per task, read by the dashboard for the job-health panel
def status_path():
    return p("status.json")


def load_status():
    return read_json(status_path(), None) or {"tasks": {}, "runs": []}


def record_run(task, ok, summary, started_utc, finished_utc, error=None, extra=None):
    s = load_status()
    rec = {"task": task, "ok": ok, "summary": summary, "started_utc": started_utc,
           "finished_utc": finished_utc, "error": error}
    if extra:
        rec.update(extra)
    s.setdefault("tasks", {})[task] = rec
    s.setdefault("runs", []).append(rec)
    s["runs"] = s["runs"][-200:]
    s["last_run"] = rec
    write_json(status_path(), s)
    return rec
