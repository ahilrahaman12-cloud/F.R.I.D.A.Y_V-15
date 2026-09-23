"""Privacy regression tests: nothing beyond the prompt leaves the machine by default."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module
import config
from vision.screen_observer import ScreenObserver


class _StubMemory:
    def context(self, query: str = "") -> str:
        return "No saved memory is available."

    def append_lesson(self, lesson: str) -> None:
        pass

    def log_activity(self, event: str) -> None:
        self.last_event = event

    def record_turn(self, speaker: str, text: str) -> None:
        self.last_recorded = (speaker, text)


class _StubObserver:
    def __init__(self) -> None:
        self.enabled = False
        self.capture_calls = 0

    def latest_image(self):
        return None


class ScreenShareDefaultOffTests(unittest.TestCase):
    def test_config_defaults_are_off(self):
        with patch.dict(os.environ, {"FRIDAY_SCREEN_SHARE": "", "FRIDAY_MEMORY_LEARNING": ""}, clear=False):
            import importlib

            importlib.reload(config)
            self.assertFalse(config.SCREEN_SHARE_ENABLED)
            self.assertFalse(config.MEMORY_LEARNING_ENABLED)

    def test_disabled_observer_never_captures(self):
        observer = ScreenObserver(0.05, enabled=False)
        observer.capture_once()
        self.assertIsNone(observer.latest_image())
        self.assertIsNone(observer.status()["captured_at"])

    def test_runtime_disable_drops_existing_frame(self):
        observer = ScreenObserver(0.05, enabled=False)
        observer.enabled = True  # simulate an enabled window with a stored frame
        observer._latest_image = object()
        observer.set_enabled(False)
        self.assertIsNone(observer.latest_image())
        self.assertFalse(observer.status()["enabled"])

    def test_observer_loop_skips_capture_when_disabled(self):
        observer = ScreenObserver(0.01, enabled=False)
        with patch("vision.screen_observer.pyautogui.screenshot") as shot:
            observer.capture_once()
            shot.assert_not_called()


class LearningDefaultOffTests(unittest.TestCase):
    def test_learning_is_skipped_when_disabled(self):
        from core.brain import FridayBrain

        brain = FridayBrain(client=object(), memory=_StubMemory(), observer=_StubObserver())
        with patch.object(FridayBrain, "_capture_learning") as learning, patch(
            "core.brain.threading.Thread"
        ) as thread:
            brain._capture_learning_in_background("some prompt", "some reply")
            thread.assert_not_called()
            learning.assert_not_called()

    def test_learning_runs_when_enabled(self):
        from core.brain import FridayBrain

        brain = FridayBrain(client=object(), memory=_StubMemory(), observer=_StubObserver())
        with patch("config.MEMORY_LEARNING_ENABLED", True), patch(
            "core.brain.threading.Thread"
        ) as thread:
            brain._capture_learning_in_background("p", "r")
            thread.assert_called_once()


class ActivityLogPrivacyTests(unittest.TestCase):
    def test_finished_turn_logs_no_prompt_text(self):
        """The activity log records THAT a request ran, never WHAT it said."""
        from types import SimpleNamespace

        from core.brain import FridayBrain, _Turn

        memory = _StubMemory()
        brain = FridayBrain(client=object(), memory=memory, observer=_StubObserver())
        turn = _Turn("copy my passwords into vault/secrets.txt and erase history")
        response = SimpleNamespace(text="Done.")
        brain._finish_turn(turn, object(), response)
        event = getattr(memory, "last_event", "")
        self.assertIn("Completed request", event)
        self.assertNotIn("passwords", event)
        self.assertNotIn("erase", event)


class PrivacyApiTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {"GEMINI_API_KEY": "test-key" + "a" * 30}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._tmp = tempfile.TemporaryDirectory()
        root_patcher = patch.object(config, "PROJECT_ROOT", Path(self._tmp.name))
        root_patcher.start()
        self.addCleanup(root_patcher.stop)
        self.client = app_module.create_app().test_client()

    def tearDown(self):
        self._tmp.cleanup()

    def test_get_reports_both_switches(self):
        payload = self.client.get("/api/privacy").get_json()
        self.assertIn("screen_share", payload)
        self.assertIn("memory_learning", payload)

    def test_screen_share_toggle_persists_and_flips_observer(self):
        response = self.client.post("/api/privacy", json={"screen_share": True})
        self.assertEqual(response.get_json()["screen_share"], True)
        self.assertEqual(os.environ.get("FRIDAY_SCREEN_SHARE"), "1")
        env_text = (Path(self._tmp.name) / ".env").read_text(encoding="utf-8")
        self.assertIn("FRIDAY_SCREEN_SHARE=1", env_text)

        response = self.client.post("/api/privacy", json={"screen_share": False})
        self.assertEqual(response.get_json()["screen_share"], False)
        self.assertEqual(os.environ.get("FRIDAY_SCREEN_SHARE"), "0")

    def test_memory_learning_toggle_persists(self):
        response = self.client.post("/api/privacy", json={"memory_learning": True})
        self.assertEqual(response.get_json()["memory_learning"], True)
        self.assertTrue(config.MEMORY_LEARNING_ENABLED)
        config.MEMORY_LEARNING_ENABLED = False  # restore for other tests

    def test_empty_payload_rejected(self):
        self.assertEqual(self.client.post("/api/privacy", json={}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
