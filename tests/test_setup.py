"""Tests for the portable/embedded build flows: key setup and gating."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module
import config


def _flush_env_key():
    os.environ.pop("GEMINI_API_KEY", None)


class SetupStatusTests(unittest.TestCase):
    def setUp(self):
        _flush_env_key()
        self.client = app_module.create_app().test_client()

    def tearDown(self):
        _flush_env_key()

    def test_status_reports_key_source_none_when_unset(self):
        payload = self.client.get("/api/setup/status").get_json()
        self.assertFalse(payload["needs_setup"])
        self.assertEqual(payload["key_source"], "none")
        self.assertEqual(payload["status"], "NEEDS_API_KEY")

    def test_status_reports_env_key_when_set(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k" * 39}, clear=False):
            payload = self.client.get("/api/setup/status").get_json()
        self.assertEqual(payload["key_source"], "env")
        self.assertEqual(payload["status"], "OPERATIONAL")


class PortableModeTests(unittest.TestCase):
    """FRIDAY_PORTABLE=1 gates the UI behind the setup page."""

    def setUp(self):
        _flush_env_key()
        patcher = patch.object(app_module, "PORTABLE_MODE", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = app_module.create_app().test_client()

    def tearDown(self):
        _flush_env_key()

    def test_root_shows_setup_page_when_no_key(self):
        response = self.client.get("/")
        self.assertIn(b"API KEY REQUIRED", response.data)

    def test_root_shows_main_hud_once_key_exists(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k" * 39}, clear=False):
            response = self.client.get("/")
        self.assertIn(b"F.R.I.D.A.Y. Core Command Center", response.data)

    def test_office_redirects_to_setup_when_no_key(self):
        response = self.client.get("/office")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/setup"))

    def test_health_reports_needs_api_key_in_portable_mode(self):
        payload = self.client.get("/api/health").get_json()
        self.assertEqual(payload["status"], "NEEDS_API_KEY")

    def test_health_ok_in_portable_mode_with_key(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k" * 39}, clear=False):
            payload = self.client.get("/api/health").get_json()
        self.assertEqual(payload["status"], "OPERATIONAL")


class EmbeddedModeTests(unittest.TestCase):
    def setUp(self):
        _flush_env_key()
        self.client = app_module.create_app().test_client()

    def test_status_flags_embedded_key(self):
        with patch.object(config, "_EMBEDDED_API_KEY", "embedded-test-key-0123456789"):
            payload = self.client.get("/api/setup/status").get_json()
        self.assertTrue(payload["embedded_key"])
        self.assertEqual(payload["key_source"], "embedded")


class SaveApiKeyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(config, "PROJECT_ROOT", Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        _flush_env_key()

    def tearDown(self):
        _flush_env_key()
        self._tmp.cleanup()

    def test_save_writes_env_and_activates_key(self):
        self.assertTrue(config.save_api_key_to_env("AIza" + "a" * 31))
        self.assertTrue((Path(self._tmp.name) / ".env").exists())
        self.assertEqual(os.environ.get("GEMINI_API_KEY"), "AIza" + "a" * 31)
        self.assertEqual(config.key_source(), "env")

    def test_save_replaces_existing_key_line(self):
        (Path(self._tmp.name) / ".env").write_text(
            "GEMINI_API_KEY=oldkey\nOTHER_SETTING=1\n", encoding="utf-8"
        )
        self.assertTrue(config.save_api_key_to_env("AIza" + "b" * 31))
        text = (Path(self._tmp.name) / ".env").read_text(encoding="utf-8")
        self.assertIn("GEMINI_API_KEY=AIzabbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb31"[:14], text)
        self.assertNotIn("oldkey", text)
        self.assertIn("OTHER_SETTING=1", text)

    def test_save_rejects_garbage_key(self):
        self.assertFalse(config.save_api_key_to_env("short"))
        self.assertFalse(config.save_api_key_to_env("has spaces in it"))
        self.assertFalse(config.save_api_key_to_env(""))
        self.assertIsNone(os.environ.get("GEMINI_API_KEY"))

    def test_save_accepts_new_format_key(self):
        """New Google key format ("AQ.") must pass validation and persist."""
        key = "AQ." + "A" * 8 + "-" + "b" * 30
        self.assertTrue(config.save_api_key_to_env(key))
        self.assertEqual(os.environ.get("GEMINI_API_KEY"), key)
        self.assertIn(f"GEMINI_API_KEY={key}", (Path(self._tmp.name) / ".env").read_text(encoding="utf-8"))


class BackendSelectionTests(unittest.TestCase):
    """GEMINI_BACKEND picks the API surface; AQ. keys may need vertex."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(config, "PROJECT_ROOT", Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_backend_is_gemini(self):
        with patch.dict(os.environ, {"GEMINI_BACKEND": ""}, clear=False):
            client = config.build_genai_client("k" * 39)
        self.assertFalse(client.vertexai)

    def test_vertex_backend_sets_vertexai_true(self):
        with patch.dict(os.environ, {"GEMINI_BACKEND": "vertex"}, clear=False):
            client = config.build_genai_client("AQ." + "a" * 30)
        self.assertTrue(client.vertexai)

    def test_backend_aliases_normalize_to_vertex(self):
        for alias in ("vertexai", "aiplatform", "express"):
            with patch.dict(os.environ, {"GEMINI_BACKEND": alias}, clear=False):
                client = config.build_genai_client("k" * 39)
            self.assertTrue(client.vertexai, alias)


class SetupRouteTests(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tmp = tempfile.TemporaryDirectory()

    def setUp(self):
        _flush_env_key()
        # Redirect writes to a temp dir; otherwise /api/setup/key would
        # overwrite the real .env next to the project.
        root_patcher = patch.object(config, "PROJECT_ROOT", Path(self._tmp.name))
        root_patcher.start()
        self.addCleanup(root_patcher.stop)
        portable_patcher = patch.object(app_module, "PORTABLE_MODE", True)
        portable_patcher.start()
        self.addCleanup(portable_patcher.stop)
        self.client = app_module.create_app().test_client()

    def tearDown(self):
        _flush_env_key()

    def test_key_route_rejects_bad_key(self):
        response = self.client.post("/api/setup/key", json={"api_key": "nope"})
        self.assertEqual(response.status_code, 400)

    def test_key_route_saves_valid_key(self):
        response = self.client.post("/api/setup/key", json={"api_key": "AIza" + "c" * 31})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "SUCCESS")
        self.assertEqual(config.key_source(), "env")


if __name__ == "__main__":
    unittest.main()
