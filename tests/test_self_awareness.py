"""Tests for self-awareness snapshot, /api/self, and TTS helpers."""

import unittest

import app as app_module
import core.self_awareness as sa_module
from core.self_awareness import SelfAwareness


class _StubMemory:
    vault_dir = __import__("pathlib").Path(".")

    def memory_summary(self) -> str:
        return "working window 1/12 turns (10/6000 chars), 3 semantic vectors (hash backend), 2 state keys, 5 vault notes"


class _StubObserver:
    def status(self):
        return {"running": True, "enabled": False, "captured_at": None, "interval_seconds": 2}


class SelfAwarenessTests(unittest.TestCase):
    def setUp(self):
        self.aware = SelfAwareness(_StubMemory(), observer=_StubObserver())

    def test_snapshot_has_all_sections(self):
        snap = self.aware.snapshot()
        for section in ("identity", "live_state", "capabilities", "memory_summary"):
            self.assertIn(section, snap)
        self.assertEqual(snap["identity"]["name"], "F.R.I.D.A.Y.")
        self.assertEqual(snap["identity"]["install_mode"], "source")

    def test_describe_contains_grounded_facts(self):
        text = self.aware.describe()
        self.assertIn("F.R.I.D.A.Y.", text)
        self.assertIn("Local time", text)
        self.assertIn("working window", text)

    def test_request_count_increments(self):
        before = self.aware.snapshot()["live_state"]["request_count"]
        self.aware.note_request()
        self.assertEqual(self.aware.snapshot()["live_state"]["request_count"], before + 1)

    def test_capabilities_come_from_provider(self):
        self.aware.set_tool_provider(lambda: ["zeta_tool", "alpha_tool"])
        self.assertEqual(self.aware.snapshot()["capabilities"], ["alpha_tool", "zeta_tool"])

    def test_describe_never_raises_when_probes_fail(self):
        broken = SelfAwareness(_StubMemory(), observer=None)

        class _Boom:
            def status(self):
                raise RuntimeError("no display")

        broken._observer = _Boom()
        self.assertIn("Vision: disabled", broken.describe())


class ApiSelfTests(unittest.TestCase):
    def test_self_endpoint_returns_snapshot(self):
        class _Aware:
            def snapshot(self):
                return {"identity": {"name": "F.R.I.D.A.Y."}, "live_state": {}, "capabilities": [], "memory_summary": "ok"}

        class _Brain:
            self_awareness = _Aware()

        client = app_module.create_app(_Brain()).test_client()
        response = client.get("/api/self")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["identity"]["name"], "F.R.I.D.A.Y.")


class PcmToWavTests(unittest.TestCase):
    def test_wraps_pcm_in_valid_wav_header(self):
        pcm = b"\x00\x00\x00\x00"
        wav = app_module._pcm_to_wav(pcm, "audio/L16;rate=24000")
        self.assertEqual(wav[:4], b"RIFF")
        self.assertEqual(wav[8:12], b"WAVE")
        self.assertEqual(len(wav), 44 + len(pcm))
        riff_size = int.from_bytes(wav[4:8], "little")
        self.assertEqual(riff_size, 36 + len(pcm))

    def test_sample_rate_is_parsed_from_mime(self):
        import struct

        pcm = b"\x00\x00"
        wav = app_module._pcm_to_wav(pcm, "audio/L16;rate=48000")
        sample_rate = struct.unpack("<I", wav[24:28])[0]
        self.assertEqual(sample_rate, 48000)

    def test_missing_rate_falls_back_to_24k(self):
        import struct

        wav = app_module._pcm_to_wav(b"\x00\x00", "audio/L16")
        sample_rate = struct.unpack("<I", wav[24:28])[0]
        self.assertEqual(sample_rate, 24000)


if __name__ == "__main__":
    unittest.main()
