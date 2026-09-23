"""Tests for the V14 layered memory system (working, state, semantic, facade)."""

import tempfile
import unittest
from pathlib import Path

from memory.layered import LayeredMemory
from memory.semantic import hash_embedding
from memory.state import StateStore
from memory.working import WorkingMemory


class WorkingMemoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.mirror = Path(self._tmp.name) / "Session_Window.md"
        self.working = WorkingMemory(max_chars=200, max_turns=4, mirror_path=self.mirror)

    def tearDown(self):
        self._tmp.cleanup()

    def test_turns_are_bounded_by_count(self):
        for index in range(10):
            self.working.add("user", f"message {index}")
        self.assertEqual(len(self.working.turns()), 4)

    def test_turns_are_bounded_by_chars(self):
        self.working.add("user", "x" * 150)
        self.working.add("user", "y" * 150)
        self.assertLessEqual(sum(len(t.text) for t in self.working.turns()), 200)

    def test_mirror_file_is_written(self):
        self.working.add("user", "hello world")
        self.assertTrue(self.mirror.exists())
        self.assertIn("hello world", self.mirror.read_text(encoding="utf-8"))

    def test_empty_text_is_ignored(self):
        self.working.add("user", "   ")
        self.assertEqual(self.working.turns(), [])


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = StateStore(db_path=Path(self._tmp.name) / "state.sqlite3")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_set_then_get_roundtrip(self):
        self.assertTrue(self.store.set("system/voice", "on"))
        self.assertEqual(self.store.get("system/voice"), "on")

    def test_get_missing_key_returns_default(self):
        self.assertIsNone(self.store.get("nope"))
        self.assertEqual(self.store.get("nope", "fallback"), "fallback")

    def test_values_survive_reopen(self):
        self.store.set("system/counter", "42")
        reopened = StateStore(db_path=self.store.db_path)
        try:
            self.assertEqual(reopened.get("system/counter"), "42")
        finally:
            reopened.close()

    def test_keys_and_count(self):
        self.store.set("a", "1")
        self.store.set("b", "2")
        self.assertEqual(self.store.count(), 2)
        self.assertIn("a", self.store.keys())

    def test_delete_removes_key(self):
        self.store.set("gone", "1")
        self.store.delete("gone")
        self.assertIsNone(self.store.get("gone"))


class SemanticTests(unittest.TestCase):
    def test_hash_embedding_is_deterministic_and_normalized(self):
        first = hash_embedding("friday desktop assistant")
        second = hash_embedding("friday desktop assistant")
        self.assertEqual(first, second)
        norm = sum(value * value for value in first) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=5)

    def test_hash_embedding_of_empty_text_is_zero_vector(self):
        self.assertEqual(set(hash_embedding("")), {0.0})


class LayeredMemoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LayeredMemory(
            vault_dir=Path(self._tmp.name) / "vault",
            state_db_path=Path(self._tmp.name) / "state.sqlite3",
        )
        # Keep tests hermetic: use the local hash backend.
        self.store.semantic._embedder = type("E", (), {"backend_name": "hash", "dims": 256, "embed": staticmethod(hash_embedding)})()

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_is_drop_in_replacement_for_memory_store(self):
        self.store.append_preference("Prefers concise answers")
        self.store.append_lesson("Always verify clicks landed")
        self.store.log_activity("Test event")
        text = self.store.profile_file.read_text(encoding="utf-8")
        self.assertIn("Prefers concise answers", text)
        self.assertIn("Always verify clicks landed", self.store.notes_file.read_text(encoding="utf-8"))
        self.assertIn("Test event", self.store.activity_file.read_text(encoding="utf-8"))

    def test_working_turns_recorded_and_mirrored(self):
        self.store.record_turn("user", "hello friday")
        self.store.record_turn("friday", "good evening")
        mirror = self.store.vault_dir / "Session_Window.md"
        self.assertTrue(mirror.exists())
        self.assertIn("hello friday", mirror.read_text(encoding="utf-8"))

    def test_state_roundtrip(self):
        self.assertTrue(self.store.set_state("test/key", "value"))
        self.assertEqual(self.store.get_state("test/key"), "value")

    def test_context_includes_preferences(self):
        self.store.append_preference("Prefers dark mode")
        self.assertIn("Prefers dark mode", self.store.context("dark mode"))

    def test_memory_summary_lists_layers(self):
        summary = self.store.memory_summary()
        for fragment in ("working window", "semantic", "state keys", "vault notes"):
            self.assertIn(fragment, summary)


if __name__ == "__main__":
    unittest.main()
