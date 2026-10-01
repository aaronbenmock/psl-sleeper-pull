"""Preferences file (engine/prefs.py) and the synthesis metadata fallback (engine/analysis/news.py).

Run from the repo root:  python -m unittest tests.test_prefs -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from engine import prefs  # noqa: E402
from engine.analysis import news  # noqa: E402


class PrefsTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "preferences.json")

    def tearDown(self):
        shutil.rmtree(self.d)

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_committed_file_says_no_te_and_leftover_tendency(self):
        p, note = prefs.load()
        self.assertIsNone(note)
        self.assertEqual(p["exclude_positions_from_claims"], ["TE"])
        self.assertTrue(p["faab_leftover_tendency"])

    def test_missing_file_falls_back_to_defaults(self):
        p, note = prefs.load(self.path)
        self.assertEqual(p, prefs.DEFAULTS)
        self.assertIn("not found", note)

    def test_broken_file_falls_back_with_a_note(self):
        self.write("{not json")
        p, note = prefs.load(self.path)
        self.assertEqual(p, prefs.DEFAULTS)
        self.assertIn("could not be read", note)

    def test_unknown_keys_ignored_and_types_checked(self):
        self.write(json.dumps({"exclude_positions_from_claims": ["te", 3], "faab_leftover_tendency": "yes", "other": 1}))
        p, note = prefs.load(self.path)
        self.assertEqual(p["exclude_positions_from_claims"], ["TE"])
        self.assertFalse(p["faab_leftover_tendency"])
        self.assertNotIn("other", p)

    def test_defaults_are_not_shared_between_loads(self):
        p, _ = prefs.load(self.path)
        p["exclude_positions_from_claims"].append("QB")
        self.assertEqual(prefs.DEFAULTS["exclude_positions_from_claims"], [])


class SynthesisMetaTests(unittest.TestCase):
    def test_new_fields_win(self):
        w, key, label = news.synthesis_meta({"synthesis_written_at": "2026-10-07T17:40:00Z", "generated_at_utc": "x",
                                             "source": "desktop-scheduled-task"}, "")
        self.assertEqual((w, key), ("2026-10-07T17:40:00Z", "desktop-scheduled-task"))
        self.assertIn("Aaron's PC", label)

    def test_old_file_falls_back_to_generated_at_and_a_guessed_source(self):
        w, key, _ = news.synthesis_meta({"generated_at_utc": "2026-09-30T21:26:11Z", "source": "scheduled Claude task (desktop app)"}, "")
        self.assertEqual((w, key), ("2026-09-30T21:26:11Z", "desktop-scheduled-task"))
        _, key, _ = news.synthesis_meta({"source": "Anthropic API (claude-opus-5) inside GitHub Actions"}, "")
        self.assertEqual(key, "anthropic-api-action")

    def test_markdown_header_is_the_last_fallback(self):
        md = "<!-- generated 2026-09-23T17:15:00Z by scheduled Claude task -->\n## Heading"
        w, key, _ = news.synthesis_meta({}, md)
        self.assertEqual((w, key), ("2026-09-23T17:15:00Z", "desktop-scheduled-task"))

    def test_cloud_source_is_labelled(self):
        _, key, label = news.synthesis_meta({"source": "cloud-scheduled-task"}, "")
        self.assertEqual(key, "cloud-scheduled-task")
        self.assertIn("cloud", label)


if __name__ == "__main__":
    unittest.main()
