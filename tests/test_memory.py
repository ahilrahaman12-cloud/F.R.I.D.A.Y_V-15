"""Tests for memory store dedup, trimming, and vault fallback."""

import tempfile
import unittest
from pathlib import Path

from memory.store import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        self.store = MemoryStore(vault_dir=self.vault)

    def tearDown(self):
        self._tmp.cleanup()

    def test_duplicate_preference_is_not_written_twice(self):
        self.store.append_preference("Prefers concise answers")
        self.store.append_preference("Prefers concise answers")
        text = self.store.profile_file.read_text(encoding="utf-8")
        self.assertEqual(text.count("Prefers concise answers"), 1)

    def test_distinct_preferences_are_both_written(self):
        self.store.append_preference("Prefers concise answers")
        self.store.append_preference("Works in EU timezone")
        text = self.store.profile_file.read_text(encoding="utf-8")
        self.assertIn("Prefers concise answers", text)
        self.assertIn("Works in EU timezone", text)

    def test_activity_log_is_timestamped(self):
        self.store.log_activity("Test event")
        text = self.store.activity_file.read_text(encoding="utf-8")
        self.assertIn("Test event", text)
        self.assertIn("[", text)

    def test_context_includes_preferences(self):
        self.store.append_preference("Prefers dark mode")
        context = self.store.context("dark mode")
        self.assertIn("Prefers dark mode", context)


if __name__ == "__main__":
    unittest.main()
