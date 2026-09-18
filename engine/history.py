"""Historical data layer for the offline backtest harness (stdlib only, no Sleeper dependency).

Downloads nflverse release assets into data/history/ and records a manifest (source URL, download
time, sha256, byte size, row count, column list) so a rerun is reproducible. The raw files are
large (about 200 MB for play-by-play) and are gitignored; the manifest is committed.

Files per season S (2014..2026):
  stats_player_week_S.csv   nflverse weekly player stats (150 columns, identical 2015 through 2026)
  play_by_play_S.csv.gz     nflverse play-by-play, needed for the defense categories that the weekly
                            stats do not carry (three-and-outs, fourth-down stops, points allowed)
                            and for 40-plus-yard touchdowns and red-zone touches.

Run: python engine.py histbacktest --download   (or histbacktest alone, which downloads what is missing)
"""
import csv
import gzip
import hashlib
import io
import json
import os
import urllib.request

from . import config, store
from .timeutil import now_utc, iso

RELEASE = "https://github.com/nflverse/nflverse-data/releases/download"
SEASONS = list(range(2014, 2027))       # 2014 supplies priors for 2015; 2026 is partial and is used only for the scoring gate
HIST_DIR = os.path.join(config.DATA_DIR, "history")

ASSETS = {
    "stats": ("stats_player/stats_player_week_{s}.csv", "stats_player_week_{s}.csv"),
    "pbp": ("pbp/play_by_play_{s}.csv.gz", "play_by_play_{s}.csv.gz"),
}


def hist_dir():
    return os.path.join(config.DATA_DIR, "history")


def manifest_path():
    return os.path.join(hist_dir(), "manifest.json")


def load_manifest():
    return store.read_json(manifest_path(), {"files": {}}) or {"files": {}}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def open_text(path):
    if path.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", newline="")
    return open(path, encoding="utf-8", newline="")


def _describe(path):
    """Row count and column list of a CSV (plain or gzip)."""
    with open_text(path) as f:
        r = csv.reader(f)
        header = next(r)
        n = sum(1 for _ in r)
    return n, header


def fetch(kind, season, force=False, quiet=False):
    """Download one asset if missing (or force). Returns the local path, or None if unavailable."""
    url_t, name_t = ASSETS[kind]
    url = RELEASE + "/" + url_t.format(s=season)
    path = os.path.join(hist_dir(), name_t.format(s=season))
    man = load_manifest()
    key = os.path.basename(path)
    if os.path.exists(path) and not force and key in man["files"]:
        return path
    os.makedirs(hist_dir(), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "psl-fantasy-engine/2.0 (stdlib urllib)"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp, open(path + ".part", "wb") as out:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
    except Exception as e:  # noqa: BLE001
        if os.path.exists(path + ".part"):
            os.remove(path + ".part")
        if not quiet:
            print(f"history: {key} unavailable ({e})")
        return None
    os.replace(path + ".part", path)
    n, header = _describe(path)
    man["files"][key] = {"kind": kind, "season": season, "url": url, "downloaded_at_utc": iso(now_utc()),
                         "sha256": _sha256(path), "bytes": os.path.getsize(path), "rows": n, "columns": header}
    man["generated_at_utc"] = iso(now_utc())
    man["note"] = ("Raw files are gitignored (too large). Re-run `python engine.py histbacktest --download` to "
                   "recreate them; compare sha256 here to confirm the same bytes came back.")
    store.write_json(manifest_path(), man)
    if not quiet:
        print(f"history: {key} {os.path.getsize(path):,} bytes, {n:,} rows")
    return path


def ensure(seasons=None, kinds=("stats", "pbp"), quiet=False):
    """Download whatever is missing. Returns {kind: {season: path}}."""
    out = {k: {} for k in kinds}
    for s in seasons or SEASONS:
        for k in kinds:
            p = fetch(k, s, quiet=quiet)
            if p:
                out[k][s] = p
    return out


def verify():
    """Re-hash every cached file against the manifest. Returns list of (file, ok, detail)."""
    man = load_manifest()
    res = []
    for key, rec in sorted(man["files"].items()):
        path = os.path.join(hist_dir(), key)
        if not os.path.exists(path):
            res.append((key, False, "missing"))
            continue
        h = _sha256(path)
        res.append((key, h == rec["sha256"], "sha256 ok" if h == rec["sha256"] else "sha256 differs"))
    return res
