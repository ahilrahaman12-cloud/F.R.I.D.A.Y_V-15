"""Route-level tests using a stubbed brain so no API key is required."""

import io
import os
import unittest
from unittest.mock import patch

import app as app_module
from app import create_app


class _StubBrain:
    def __init__(self):
        self.reset_calls = 0
        self.last_transcription = None

    async def think(self, prompt: str):
        return {"status": "SUCCESS", "response": f"echo:{prompt}"}

    async def resolve_confirmation(self, approved: bool):
        return {"status": "SUCCESS" if approved else "CANCELLED", "response": ""}

    async def resolve_tool_approval(self, approved: bool):
        return {"status": "SUCCESS" if approved else "CANCELLED", "response": ""}

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str):
        self.last_transcription = (len(audio_bytes), mime_type)
        return {"status": "SUCCESS", "response": "hello from voice"}

    def reset_conversation(self) -> None:
        self.reset_calls += 1


class AppRouteTests(unittest.TestCase):
    def setUp(self):
        self.brain = _StubBrain()
        # Route gating calls config.has_api_key(); pin a key so these tests
        # stay hermetic even when a sibling module flushed GEMINI_API_KEY.
        env_patcher = patch.dict(os.environ, {"GEMINI_API_KEY": "test-key" + "a" * 30}, clear=False)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        self.client = create_app(self.brain).test_client()

    def test_chat_returns_echo(self):
        response = self.client.post("/api/chat", json={"prompt": "hi"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["response"], "echo:hi")

    def test_chat_rejects_empty_prompt(self):
        response = self.client.post("/api/chat", json={"prompt": "   "})
        self.assertEqual(response.status_code, 400)

    def test_reset_route_clears_conversation(self):
        response = self.client.post("/api/reset", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.brain.reset_calls, 1)

    def test_transcribe_route_forwards_audio(self):
        response = self.client.post(
            "/api/transcribe",
            data={"audio": (io.BytesIO(b"fake-bytes"), "speech.webm")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["response"], "hello from voice")
        self.assertEqual(self.brain.last_transcription, (10, "audio/webm"))

    def test_transcribe_route_requires_audio(self):
        response = self.client.post("/api/transcribe", data={})
        self.assertEqual(response.status_code, 400)

    def test_health_reports_component_checks(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn(payload["status"], {"OPERATIONAL", "DEGRADED"})
        for key in ("gemini_key", "model", "memory_vault", "screen_observer", "telemetry"):
            self.assertIn(key, payload["checks"])

    def test_health_flags_missing_gemini_key_as_degraded(self):
        from unittest.mock import patch
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}, clear=False):
            response = self.client.get("/api/health")
        payload = response.get_json()
        if payload["checks"]["gemini_key"] == "missing":
            self.assertEqual(payload["status"], "DEGRADED")

    def test_office_page_renders(self):
        response = self.client.get("/office")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"OFFICE DOCK", response.data)


class KeylessPortableRouteTests(unittest.TestCase):
    """Routes that build a brain lazily must not 500 on keyless installs."""

    def setUp(self):
        patcher = patch.object(app_module, "PORTABLE_MODE", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        env_patcher = patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        self.client = create_app().test_client()

    def test_reset_without_key_returns_setup_error_not_500(self):
        response = self.client.post("/api/reset", json={})
        self.assertEqual(response.status_code, 503)
        self.assertIn("setup", response.get_json()["message"].lower())

    def test_confirm_without_key_returns_setup_error_not_500(self):
        self.assertEqual(self.client.post("/api/confirm", json={"approve": True}).status_code, 503)
        self.assertEqual(self.client.post("/api/confirm/tools", json={"approve": True}).status_code, 503)

    def test_reset_works_once_key_is_configured(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k" * 39}, clear=False):
            response = self.client.post("/api/reset", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
