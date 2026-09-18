#!/usr/bin/env python3
"""Compatibility shim. The v1.1 weekly pull now lives in engine/pull.py (v1.2) and is run by
`python engine.py pull`. This file keeps the old command working:

  python sleeper_weekly_pull.py [--completed-week N]
"""
import os
import runpy
import sys

if __name__ == "__main__":
    sys.argv = ["engine.py", "pull"] + sys.argv[1:]
    runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine.py"), run_name="__main__")
