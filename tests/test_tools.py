"""Tests for workspace-constrained file tools and tool hardening."""

import unittest
from pathlib import Path
from unittest.mock import patch

from core import tools


class WorkspaceToolsTests(unittest.TestCase):
    def test_write_and_list_workspace_file(self):
        test_workspace = Path(__file__).resolve().parents[1] / "workspace"
        with patch.object(tools, "WORKSPACE_DIR", test_workspace):
            result = tools.write_workspace_file("test-output/today.txt", "Hello")
            listing = tools.list_workspace_files("test-output")
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(listing["items"], ["today.txt"])

    def test_parent_directory_escape_is_rejected(self):
        result = tools.write_workspace_file("../outside.txt", "No")
        self.assertIn("error", result)


class OpenUrlTests(unittest.TestCase):
    def test_plain_domain_gets_https(self):
        with patch("webbrowser.open") as browser_open:
            result = tools.open_url("example.com")
        browser_open.assert_called_once_with("https://example.com")
        self.assertEqual(result["status"], "SUCCESS")

    def test_non_http_scheme_is_rejected(self):
        result = tools.open_url("javascript:alert(1)")
        self.assertIn("error", result)

    def test_empty_url_is_rejected(self):
        result = tools.open_url("   ")
        self.assertIn("error", result)


class MediaToolsTests(unittest.TestCase):
    def test_spotify_search_opens_browser(self):
        with patch("webbrowser.open") as browser_open:
            result = tools.play_on_spotify("Daft Punk")
        browser_open.assert_called_once()
        url = browser_open.call_args[0][0]
        self.assertIn("open.spotify.com/search", url)
        self.assertIn("Daft", url)
        self.assertEqual(result["status"], "SUCCESS")

    def test_spotify_empty_query_is_rejected(self):
        result = tools.play_on_spotify("   ")
        self.assertIn("error", result)

    def test_youtube_search_opens_browser(self):
        with patch("webbrowser.open") as browser_open:
            result = tools.play_on_youtube("lofi beats")
        browser_open.assert_called_once()
        url = browser_open.call_args[0][0]
        self.assertIn("youtube.com/results", url)
        self.assertIn("search_query=", url)
        self.assertEqual(result["status"], "SUCCESS")

    def test_media_key_rejects_unknown_names(self):
        result = tools.press_media_key("eject")
        self.assertIn("error", result)

    def test_media_key_accepts_play_pause(self):
        with patch("pyautogui.press") as press:
            result = tools.press_media_key("play_pause")
        press.assert_called_once_with("playpause")
        self.assertEqual(result["status"], "SUCCESS")


class ShutdownValidationTests(unittest.TestCase):
    def test_invalid_action_is_rejected_without_side_effects(self):
        result = tools.shutdown_computer("format_everything")
        self.assertIn("error", result)

    def test_logoff_rejects_delay(self):
        result = tools.shutdown_computer("logoff", delay_seconds=30)
        self.assertIn("error", result)

    def test_cancel_is_whitelisted(self):
        with patch("os.system") as system:
            result = tools.shutdown_computer("cancel")
        system.assert_called_once_with("shutdown /a")
        self.assertEqual(result["status"], "SUCCESS")


class CustomLinkTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.links_file = Path(self._tmp.name) / "links.json"
        patcher = patch.object(tools, "LINKS_FILE", self.links_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_and_open_link(self):
        saved = tools.save_custom_link("Docs", "docs.google.com")
        self.assertEqual(saved["status"], "SUCCESS")
        self.assertEqual(self.links_file.read_text(encoding="utf-8").count("docs.google.com"), 1)

        with patch("webbrowser.open") as browser_open:
            opened = tools.open_custom_link("DOCS")  # name is case-insensitive
        browser_open.assert_called_once_with("https://docs.google.com")
        self.assertEqual(opened["status"], "SUCCESS")

    def test_open_unknown_link_lists_known_names(self):
        result = tools.open_custom_link("nope")
        self.assertIn("error", result)
        self.assertIn("none saved yet", result["error"])

    def test_save_rejects_bad_name_and_url(self):
        self.assertIn("error", tools.save_custom_link("", "https://x.com"))
        self.assertIn("error", tools.save_custom_link("bad;name", "https://x.com"))
        self.assertIn("error", tools.save_custom_link("ok", "javascript:alert(1)"))

    def test_list_links_returns_empty_dict_when_missing(self):
        result = tools.list_custom_links()
        self.assertEqual(result["links"], {})


if __name__ == "__main__":
    unittest.main()
