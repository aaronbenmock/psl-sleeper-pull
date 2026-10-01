"""Aaron's preferences (config/preferences.json), read once at build time.

Every key has a default, unknown keys are ignored, and a missing or unreadable file falls back to
the defaults with a note, so a bad edit can never take the build down."""
import json
import os

PATH = os.path.join("config", "preferences.json")
DEFAULTS = {
    "exclude_positions_from_claims": [],   # positions never recommended as claims (shown collapsed instead)
    "faab_leftover_tendency": False,       # True: he usually finishes with FAAB unspent, so scale bids up
}


def load(path=None):
    """Returns (prefs dict, note or None)."""
    path = path or PATH
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    if not os.path.exists(path):
        return out, f"{path} not found; using defaults"
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        return out, f"{path} could not be read ({e}); using defaults"
    if not isinstance(raw, dict):
        return out, f"{path} is not a JSON object; using defaults"
    ex = raw.get("exclude_positions_from_claims")
    if isinstance(ex, list):
        out["exclude_positions_from_claims"] = [str(p).upper() for p in ex if isinstance(p, str)]
    if isinstance(raw.get("faab_leftover_tendency"), bool):
        out["faab_leftover_tendency"] = raw["faab_leftover_tendency"]
    return out, None
