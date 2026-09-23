"""Production-hardening regression tests.

Covers: version reporting, no internal-detail leakage on 500s, concurrent
request handling through the shared event loop, and installer/app version
sync.
"""

import concurrent.futures
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module
import config

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _with_key():
    return patch.dict(os.environ, {"GEMINI_API_KEY": "test-key" + "a" * 30}, clear=False)


class _ExplodingBrain:
    """Brain whose chat path raises with juicy internal details."""

    async def think(self, prompt: str):
        raise RuntimeError(f"boom at {PROJECT_ROOT / 'secret' / 'path.py'} token=abc123")

    async def resolve_confirmation(self, approved: bool):
        return {"status": "SUCCESS", "response": ""}

    async def resolve_tool_approval(self, approved: bool):
        return {"status": "SUCCESS", "response": ""}

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str):
        return {"status": "SUCCESS", "response": ""}

    def reset_conversation(self) -> None:
        pass


class _CountingBrain:
    """Thread-safe brain for the concurrency smoke test."""

    def __init__(self) -> None:
        self.calls = 0

    async def think(self, prompt: str):
        # The app must serialize brain access; a racy counter would flake.
        current = self.calls
        self.calls = current + 1
        return {"status": "SUCCESS", "response": f"echo:{prompt}"}

    async def resolve_confirmation(self, approved: bool):
        return {"status": "SUCCESS", "response": ""}

    async def resolve_tool_approval(self, approved: bool):
        return {"status": "SUCCESS", "response": ""}

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str):
        return {"status": "SUCCESS", "response": ""}

    def reset_conversation(self) -> None:
        pass


class HealthVersionTests(unittest.TestCase):
    def setUp(self):
        patcher = _with_key()
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = app_module.create_app().test_client()

    def test_health_reports_app_version(self):
        payload = self.client.get("/api/health").get_json()
        self.assertEqual(payload["checks"]["version"], config.APP_VERSION)
        # Version must not participate in the pass/fail logic.
        self.assertIn(payload["status"], {"OPERATIONAL", "DEGRADED"})

    def test_version_matches_installer_constant(self):
        """APP_VERSION and the installer's version must never drift apart."""
        installer_source = (PROJECT_ROOT / "build" / "installer_app.py").read_text(encoding="utf-8")
        match = re.search(r'^APP_VERSION = "([^"]+)"', installer_source, re.MULTILINE)
        self.assertIsNotNone(match, "installer_app.py lost its APP_VERSION constant")
        self.assertEqual(match.group(1), config.APP_VERSION)


class NoLeak500Tests(unittest.TestCase):
    def setUp(self):
        patcher = _with_key()
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = app_module.create_app(_ExplodingBrain()).test_client()

    def test_chat_500_hides_internal_details(self):
        response = self.client.post("/api/chat", json={"prompt": "hello"})
        self.assertEqual(response.status_code, 500)
        message = response.get_json()["message"]
        self.assertNotIn(str(PROJECT_ROOT), message)
        self.assertNotIn("token=abc123", message)
        self.assertNotIn("RuntimeError", message)

    def test_tts_failure_is_sanitized(self):
        client = app_module.create_app(_ExplodingBrain()).test_client()

        class _TTSBrain(_ExplodingBrain):
            async def synthesize_speech(self, text):
                raise RuntimeError("secret internal detail")

        client = app_module.create_app(_TTSBrain()).test_client()
        response = client.post("/api/speak", json={"text": "speak"})
        # V14 contract: 503 when no Deepgram key is configured (TTS not set
        # up), 502 when a configured provider's fallback also failed. Either
        # way the message must never leak internal error details.
        self.assertIn(response.status_code, (502, 503))
        self.assertNotIn("secret internal detail", response.get_json()["message"])


class ConcurrencySmokeTests(unittest.TestCase):
    def test_parallel_chats_all_succeed(self):
        brain = _CountingBrain()
        patcher = _with_key()
        patcher.start()
        self.addCleanup(patcher.stop)
        app_module.create_app(brain)  # warm the shared loop like a real boot

        app_instance = app_module.create_app(brain)

        def send(index: int) -> int:
            client = app_instance.test_client()
            response = client.post("/api/chat", json={"prompt": f"msg-{index}"})
            return response.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(send, range(16)))

        self.assertEqual(codes, [200] * 16)
        self.assertEqual(brain.calls, 16)


if __name__ == "__main__":
    unittest.main()
