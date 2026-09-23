"""Tests for the V14 vault tools in core/tools.py."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.tools as tools


class VaultToolsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        vault = Path(self._tmp.name)
        self._patcher = patch.object(tools, "VAULT_DIR", vault)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_read_and_list_notes(self):
        result = tools.write_vault_note("notes/idea.md", "# Idea\ncontent")
        self.assertEqual(result["status"], "SUCCESS")
        read = tools.read_vault_note("notes/idea.md")
        self.assertIn("content", read["content"])
        listed = tools.list_vault_notes()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["notes"][0]["path"], "notes/idea.md")

    def test_md_extension_is_appended_automatically(self):
        result = tools.write_vault_note("Quick", "hello")
        self.assertEqual(result["status"], "SUCCESS")
        self.assertTrue((Path(self._tmp.name) / "Quick.md").exists())

    def test_append_creates_note_with_header(self):
        result = tools.append_vault_note("Log", "first entry")
        self.assertEqual(result["status"], "SUCCESS")
        text = (Path(self._tmp.name) / "Log.md").read_text(encoding="utf-8")
        self.assertIn("# Log", text)
        self.assertIn("- first entry", text)

    def test_append_adds_bullet_prefix(self):
        tools.write_vault_note("Log", "# Log\n")
        tools.append_vault_note("Log", "already plain")
        text = (Path(self._tmp.name) / "Log.md").read_text(encoding="utf-8")
        self.assertIn("- already plain", text)

    def test_path_traversal_is_rejected(self):
        for bad in ("../escape.md", "..\\escape", "a/../../b"):
            with self.subTest(path=bad):
                result = tools.write_vault_note(bad, "nope")
                self.assertIn("error", result)

    def test_invalid_characters_are_rejected(self):
        result = tools.write_vault_note("bad:name", "nope")
        self.assertIn("error", result)

    def test_read_missing_note_reports_error(self):
        result = tools.read_vault_note("does-not-exist")
        self.assertIn("error", result)

    def test_search_finds_content_and_names(self):
        tools.write_vault_note("Alpha", "the quick brown fox")
        tools.write_vault_note("Beta", "nothing relevant here")
        tools.write_vault_note("Fox_Notes", "unrelated body")
        result = tools.search_vault("quick")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["matches"][0]["note"], "Alpha.md")
        by_name = tools.search_vault("Fox")
        self.assertTrue(any(m["note"] == "Fox_Notes.md" for m in by_name["matches"]))

    def test_search_requires_query(self):
        self.assertIn("error", tools.search_vault("   "))

    def test_vault_tools_are_registered(self):
        registry = tools.available_tools()
        for name in ("list_vault_notes", "read_vault_note", "write_vault_note", "append_vault_note", "search_vault"):
            self.assertIn(name, registry)


if __name__ == "__main__":
    unittest.main()
