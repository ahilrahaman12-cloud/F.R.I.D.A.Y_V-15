"""Desktop and web entry point for F.R.I.D.A.Y."""

import asyncio
import base64
import logging
import os
import re
import struct
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, redirect, render_template, request

import config
from config import BUNDLE_DIR, MODEL_NAME, OBSIDIAN_VAULT_DIR, VAULT_DIR
from core.brain import FridayBrain
from core.tools import list_custom_links, open_custom_link, save_custom_link
from system.telemetry import get_system_state


# Runtime flags for the packaged executables.
PORTABLE_MODE = bool(os.getenv("FRIDAY_PORTABLE"))


def _setup_logging() -> None:
    """Log to a rotating file so a windowed exe stays debuggable.

    The packaged build has no console; without this, a crash leaves nothing
    behind. Debug details go to the file only — API responses stay generic so
    internal paths and library errors are never surfaced to the UI.
    """
    log_path = Path(config.PROJECT_ROOT, "friday.log")
    handler = RotatingFileHandler(log_path, maxBytes=512_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Quiet down noisy third-party loggers.
    for noisy in ("werkzeug", "urllib3", "pywebview"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


if os.getenv("FRIDAY_QUIET") != "1":  # tests stay silent
    _setup_logging()

logger = logging.getLogger("friday")

# Static assets live next to the templates, both in source runs and inside the
# PyInstaller bundle, so the frontend never depends on a CDN.
STATIC_FOLDER = str(Path(BUNDLE_DIR, "static"))


def embedded_key_present() -> bool:
    """True when this exe was built with a precompiled Gemini key."""
    return bool(str(getattr(config, "_EMBEDDED_API_KEY", "")).strip())


class AsyncLoop:
    """One persistent background event loop shared by all requests.

    ``asyncio.run()`` per request created a new loop for every chat message and
    never closed it, and Flask's default threaded server could drive the same
    FridayBrain on several loops at once. A single loop serializes brain
    coroutines safely and keeps loop-bound state (e.g. the screen observer)
    stable for the lifetime of the process.
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="friday-asyncio", daemon=True
        )
        self._thread.start()

    def run(self, coro):
        """Run a coroutine on the loop and block until it finishes."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        self._loop.close()


_async_loop = AsyncLoop()


def _pcm_to_wav(pcm: bytes, mime: str) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV container for browser playback.

    Gemini TTS returns headerless PCM (sample rate embedded in the MIME type,
    e.g. ``audio/L16;rate=24000``); browsers need a proper container, so the
    Gemini TTS fallback path wraps it before sending.
    """
    rate_match = re.search(r"rate=(\d+)", mime or "")
    sample_rate = int(rate_match.group(1)) if rate_match else 24000
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM format
        1,  # mono channel count
        sample_rate,
        sample_rate * 2,  # byte rate: 16-bit mono
        2,  # block align
        16,  # bits per sample
        b"data",
        len(pcm),
    )
    return header + pcm


def create_app(brain: FridayBrain | None = None) -> Flask:
    """Create the Flask application and allow dependency injection in tests."""
    # Frozen (PyInstaller) builds extract bundled templates and static assets
    # to the _MEIPASS bundle dir; source runs read them from disk next to this
    # file. The explicit static folder keeps the strict CSP ('self') working.
    template_folder = str(Path(BUNDLE_DIR, "templates"))
    app = Flask(__name__, template_folder=template_folder, static_folder=STATIC_FOLDER)
    assistant = brain

    @app.after_request
    def security_headers(response):
        # The templates also carry a CSP meta tag; header form covers every
        # response, including errors and static files.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    brain_lock = threading.Lock()

    def get_brain() -> FridayBrain:
        """Build the brain once; Flask's threaded server may race first use."""
        nonlocal assistant
        if assistant is None:
            with brain_lock:
                if assistant is None:
                    assistant = FridayBrain()
        return assistant

    @app.get("/")
    def index():
        if needs_setup():
            return render_template("setup.html")
        return render_template("index.html")

    @app.get("/office")
    def office():
        if needs_setup():
            return redirect("/setup")
        return render_template("office.html")

    @app.get("/setup")
    def setup():
        if not needs_setup():
            return redirect("/")
        return render_template("setup.html")

    def needs_setup() -> bool:
        """Portable build requires a key until one is saved or provided."""
        return PORTABLE_MODE and not config.has_api_key()

    def get_brain_or_error():
        """Return the brain, or an error response when no API key is configured.

        The brain needs a Gemini key at construction time; building it lazily
        for /api/reset and the confirm routes crashed with a 500 on keyless
        portable installs instead of pointing the user at setup.
        """
        if not config.has_api_key():
            return None, (
                jsonify({"status": "ERROR", "message": "No Gemini API key configured. Complete setup first."}),
                503,
            )
        return get_brain(), None

    @app.get("/api/setup/status")
    def setup_status():
        return jsonify(
            {
                "needs_setup": needs_setup(),
                "embedded_key": embedded_key_present(),
                "key_source": config.key_source(),
                "status": "OPERATIONAL" if config.has_api_key() else "NEEDS_API_KEY",
            }
        )

    @app.post("/api/setup/key")
    def setup_key():
        payload = request.get_json(silent=True) or {}
        api_key = (payload.get("api_key") or "").strip()
        if not api_key:
            return jsonify({"status": "ERROR", "message": "Paste your Gemini API key."}), 400
        if not config.save_api_key_to_env(api_key):
            return jsonify({"status": "ERROR", "message": "That does not look like a valid Gemini API key."}), 400
        return jsonify({"status": "SUCCESS", "message": "API key saved. F.R.I.D.A.Y. is online."})

    @app.get("/api/links")
    def links():
        """Saved link shortcuts for the office dashboard."""
        return jsonify(list_custom_links())

    @app.post("/api/links/open")
    def links_open():
        name = (request.get_json(silent=True) or {}).get("name", "").strip()
        if not name:
            return jsonify({"status": "ERROR", "message": "Link name required."}), 400
        return jsonify(open_custom_link(name))

    @app.post("/api/links/save")
    def links_save():
        payload = request.get_json(silent=True) or {}
        name = payload.get("name", "").strip()
        url = payload.get("url", "").strip()
        result = save_custom_link(name, url)
        status_code = 400 if result.get("error") else 200
        return jsonify(result), status_code

    @app.post("/api/chat")
    def chat():
        prompt = (request.get_json(silent=True) or {}).get("prompt", "").strip()
        if not prompt:
            return jsonify({"status": "ERROR", "response": "Prompt cannot be empty."}), 400
        try:
            return jsonify(_async_loop.run(get_brain().think(prompt)))
        except Exception:
            # Full details in friday.log; never leak internals to the client.
            logger.exception("chat request failed")
            return jsonify({"status": "ERROR", "response": "", "message": "Internal server error. See friday.log for details."}), 500

    @app.post("/api/confirm")
    def confirm():
        brain, error = get_brain_or_error()
        if error is not None:
            return error
        approved = bool((request.get_json(silent=True) or {}).get("approve", False))
        return jsonify(_async_loop.run(brain.resolve_confirmation(approved)))

    @app.post("/api/confirm/tools")
    def confirm_tools():
        brain, error = get_brain_or_error()
        if error is not None:
            return error
        approved = bool((request.get_json(silent=True) or {}).get("approve", False))
        try:
            return jsonify(_async_loop.run(brain.resolve_tool_approval(approved)))
        except Exception:
            logger.exception("tool confirmation failed")
            return jsonify({"status": "ERROR", "response": "", "message": "Internal server error. See friday.log for details."}), 500

    @app.post("/api/reset")
    def reset():
        brain, error = get_brain_or_error()
        if error is not None:
            return error
        brain.reset_conversation()
        return jsonify({"status": "SUCCESS", "response": "Conversation reset."})

    @app.post("/api/transcribe")
    def transcribe():
        """Transcribe a recorded voice note via Gemini audio understanding."""
        if "audio" not in request.files:
            return jsonify({"status": "ERROR", "response": "No audio upload."}), 400
        upload = request.files["audio"]
        audio_bytes = upload.read()
        if not audio_bytes:
            return jsonify({"status": "ERROR", "response": "Empty audio upload."}), 400
        mime = (upload.mimetype or "").lower()
        if not mime.startswith("audio/"):
            # Browsers and test clients may label voice-only webm/ogg/mp4 uploads
            # as video because of the container; normalize to the audio type.
            if any(container in mime for container in ("webm", "ogg", "wav", "mpeg", "mp4", "x-matroska")):
                mime = mime.replace("video/", "audio/", 1)
            else:
                mime = "audio/webm"
        try:
            return jsonify(_async_loop.run(get_brain().transcribe_audio(audio_bytes, mime)))
        except Exception:
            logger.exception("transcription failed")
            return jsonify({"status": "ERROR", "response": "", "message": "Transcription failed. See friday.log for details."}), 500

    @app.post("/api/speak")
    def speak():
        """Convert assistant text to speech, streamed for low latency (V14).

        Primary path: Deepgram Aura TTS MP3 streamed chunk-by-chunk so the
        browser starts speaking on the first bytes instead of waiting for the
        whole clip. Fallback: Gemini TTS returned as a playable WAV. If both
        fail the client falls back to the browser's built-in speech synthesis.
        """
        text = (request.get_json(silent=True) or {}).get("text", "").strip()
        if not text:
            return jsonify({"status": "ERROR", "response": "Nothing to speak."}), 400

        deepgram_error = ""
        if config.has_deepgram():
            try:
                upstream = requests.post(
                    "https://api.deepgram.com/v1/speak",
                    params={"model": config.DEEPGRAM_TTS_MODEL, "encoding": "mp3"},
                    headers={
                        "Authorization": f"Token {config.deepgram_api_key()}",
                        "Content-Type": "application/json",
                    },
                    json={"text": text[:2000]},
                    stream=True,
                    timeout=(3, 30),
                )
            except requests.RequestException as error:
                upstream = None
                deepgram_error = f"Deepgram TTS failed: {error}"
            else:
                if upstream.status_code == 200:
                    def generate():
                        try:
                            # Smaller chunks reach the browser sooner, trimming
                            # time-to-first-audio compared to large reads.
                            for chunk in upstream.iter_content(chunk_size=2048):
                                if chunk:
                                    yield chunk
                        finally:
                            upstream.close()

                    return Response(generate(), status=200, mimetype="audio/mpeg")
                try:
                    detail = upstream.json().get("err_msg", "") or upstream.text[:200]
                except Exception:
                    detail = upstream.text[:200]
                deepgram_error = f"Deepgram TTS failed: {detail}"
                upstream.close()

        # Fallback: Gemini TTS wrapped in a WAV container browsers can play.
        fallback_status = 503 if not config.has_deepgram() else 502
        try:
            audio_b64, mime = _async_loop.run(get_brain().synthesize_speech(text[:1200]))
        except Exception:
            logger.exception("TTS request failed")
            return jsonify(
                {"status": "ERROR", "response": "", "message": "Speech synthesis failed. See friday.log for details."}
            ), fallback_status
        if not audio_b64:
            return jsonify({"status": "ERROR", "response": "", "message": "TTS returned no audio."}), fallback_status
        # Gemini returns raw PCM; wrap it in a WAV container so every browser
        # can play it without manual sample decoding.
        try:
            wav_bytes = _pcm_to_wav(base64.b64decode(audio_b64), mime)
        except Exception:
            logger.exception("TTS fallback failed")
            return jsonify({"status": "ERROR", "response": "", "message": "TTS fallback failed. See friday.log for details."}), 500
        return Response(wav_bytes, status=200, mimetype="audio/wav")

    @app.get("/api/self")
    def self_snapshot():
        """Full self-awareness snapshot: identity, live state, capabilities."""
        try:
            return jsonify(get_brain().self_awareness.snapshot())
        except Exception:
            logger.exception("self snapshot failed")
            return jsonify({"status": "ERROR", "message": "Self-awareness unavailable."}), 503

    def privacy_state() -> dict[str, bool]:
        """Live privacy switch positions for the settings API."""
        observer = getattr(assistant, "observer", None)
        screen_share = observer.enabled if observer is not None else config.SCREEN_SHARE_ENABLED
        return {"screen_share": bool(screen_share), "memory_learning": bool(config.MEMORY_LEARNING_ENABLED)}

    @app.get("/api/privacy")
    def privacy_get():
        return jsonify({"status": "SUCCESS", **privacy_state()})

    @app.post("/api/privacy")
    def privacy_set():
        """Toggle privacy switches; persisted to .env, applied immediately."""
        payload = request.get_json(silent=True) or {}
        updated: dict[str, bool] = {}
        if "screen_share" in payload:
            want = bool(payload["screen_share"])
            if not config.set_env_value("FRIDAY_SCREEN_SHARE", "1" if want else "0"):
                return jsonify({"status": "ERROR", "message": "Could not persist the screen sharing setting."}), 500
            observer = getattr(assistant, "observer", None)
            if observer is not None:
                observer.set_enabled(want)
            else:
                # No brain yet: keep the live flag current so a brain created
                # later picks up the toggle instead of the boot-time value.
                config.SCREEN_SHARE_ENABLED = want
            updated["screen_share"] = want
        if "memory_learning" in payload:
            want = bool(payload["memory_learning"])
            if not config.set_env_value("FRIDAY_MEMORY_LEARNING", "1" if want else "0"):
                return jsonify({"status": "ERROR", "message": "Could not persist the memory learning setting."}), 500
            config.MEMORY_LEARNING_ENABLED = want
            updated["memory_learning"] = want
        if not updated:
            return jsonify({"status": "ERROR", "message": "No recognized setting in payload."}), 400
        return jsonify({"status": "SUCCESS", "updated": updated, **privacy_state()})

    @app.get("/api/health")
    def health():
        """Real component status for the boot screens; never raises."""
        checks: dict[str, str] = {}

        # Gemini key: report without raising or creating the brain.
        # In portable mode a missing key means "not set up yet", not broken.
        if config.has_api_key():
            checks["gemini_key"] = "ok"
        else:
            checks["gemini_key"] = "not_configured" if PORTABLE_MODE else "missing"
        checks["model"] = MODEL_NAME
        checks["version"] = config.APP_VERSION

        # Memory vault: prefer the configured Obsidian path, note the fallback.
        # A fresh portable install has neither; create the local vault on demand
        # so the first boot reports healthy instead of "missing".
        try:
            if OBSIDIAN_VAULT_DIR.exists() and os.access(OBSIDIAN_VAULT_DIR, os.W_OK):
                checks["memory_vault"] = "ok"
            else:
                try:
                    VAULT_DIR.mkdir(parents=True, exist_ok=True)
                except OSError:
                    pass
                checks["memory_vault"] = "fallback" if VAULT_DIR.is_dir() else "missing"
        except OSError:
            checks["memory_vault"] = "unknown"

        # Screen observer: running only if a brain was already created.
        observer = getattr(assistant, "observer", None)
        if observer is not None:
            try:
                status = observer.status()
                # "ok" only when capture is actually enabled; an idle observer
                # with screen sharing off is "standby", not degraded.
                checks["screen_observer"] = "ok" if status.get("running") and status.get("enabled") else "standby"
            except Exception:
                checks["screen_observer"] = "unknown"
        else:
            checks["screen_observer"] = "standby"

        # Telemetry: cheap probe to prove psutil works.
        try:
            get_system_state()
            checks["telemetry"] = "ok"
        except Exception:
            checks["telemetry"] = "error"

        # "model" and "version" are informational, not pass/fail checks.
        status_values = [value for key, value in checks.items() if key not in ("model", "version")]
        if PORTABLE_MODE and checks["gemini_key"] == "not_configured":
            overall = "NEEDS_API_KEY"
        else:
            overall = "OPERATIONAL" if all(
                value in {"ok", "standby", "fallback"} for value in status_values
            ) else "DEGRADED"
        return jsonify({"status": overall, "checks": checks})

    @app.get("/api/stats")
    def stats():
        return jsonify(get_system_state())

    @app.get("/api/memory")
    def memory_layers():
        """Layer-by-layer memory statistics for the HUD MEMORY panel (V14)."""
        try:
            memory = get_brain().memory
        except Exception:
            logger.exception("memory endpoint failed")
            return jsonify({"status": "ERROR", "message": "Memory unavailable. See friday.log for details."}), 500
        payload: dict = {}
        layer_stats = getattr(memory, "stats", None)
        if callable(layer_stats):
            try:
                payload.update(layer_stats())
            except Exception:
                logger.exception("memory stats failed")
                return jsonify({"status": "ERROR", "message": "Memory stats failed. See friday.log for details."}), 500
        # Paths are not JSON-serializable; expose them as strings.
        payload["vault"] = str(payload.get("vault") or getattr(memory, "vault_dir", ""))
        payload["session_file"] = str(payload.get("session_file") or "")
        payload["status"] = "SUCCESS"
        return jsonify(payload)

    return app


def run_desktop_app() -> None:
    """Start the Flask interface in a native desktop window."""
    import webview

    webview.create_window("F.R.I.D.A.Y. Assistant", create_app(), width=900, height=650, resizable=True)
    webview.start()


if __name__ == "__main__":
    # Hidden self-test entry point: FRIDAY_SELFTEST=1 runs headless checks and
    # exits, so a packaged exe can be verified without opening a GUI window.
    if os.getenv("FRIDAY_SELFTEST") == "1":
        client = create_app().test_client()
        health = client.get("/api/health").get_json()
        stats_ok = client.get("/api/stats").status_code == 200
        office_ok = client.get("/office").status_code == 200
        setup_status = client.get("/api/setup/status").get_json()
        setup_page = client.get("/setup")
        chat = client.post("/api/chat", json={"prompt": "tell me a joke"}).get_json()
        # Extra coverage: every route + the local tool layer.
        reset_ok = client.post("/api/reset").get_json().get("status") == "SUCCESS"
        confirm_empty = client.post("/api/confirm", json={"approve": True}).get_json().get("status")
        tools_empty = client.post("/api/confirm/tools", json={"approve": True}).get_json().get("status")
        transcribe_empty = client.post("/api/transcribe").status_code == 400
        speak_empty = client.post("/api/speak", json={"text": ""}).status_code == 400
        chat_empty = client.post("/api/chat", json={"prompt": ""}).status_code == 400
        bad_key_route = client.post("/api/setup/key", json={"api_key": "nope"}).status_code
        sysinfo = __import__("core.tools", fromlist=["get_system_info"]).get_system_info()
        screen_size = __import__("core.tools", fromlist=["get_screen_size"]).get_screen_size()
        main_page_ok = client.get("/").status_code == 200
        from config import PROJECT_ROOT

        print("SELFPATHS", {
            "frozen": bool(getattr(sys, "frozen", False)),
            "project_root": str(PROJECT_ROOT),
            "env_file_exists": (PROJECT_ROOT / ".env").exists(),
        })
        print("SELFTEST", {
            "health": health.get("status"),
            "vault": health.get("checks", {}).get("memory_vault"),
            "telemetry": health.get("checks", {}).get("telemetry"),
            "stats": stats_ok,
            "office": office_ok,
            "setup_page": setup_page.status_code,
            "needs_setup": setup_status.get("needs_setup"),
            "key_source": setup_status.get("key_source"),
            "chat_gate": chat.get("status"),
            # New checks:
            "main_page": main_page_ok,
            "reset": reset_ok,
            "confirm_no_pending": confirm_empty,
            "tools_confirm_no_pending": tools_empty,
            "transcribe_rejects_empty": transcribe_empty,
            "speak_rejects_empty": speak_empty,
            "chat_rejects_empty": chat_empty,
            "setup_key_rejects_bad": bad_key_route,
            "sysinfo": sysinfo.get("operating_system"),
            "screen": f"{screen_size.get('width')}x{screen_size.get('height')}",
            "python": sysinfo.get("python_version"),
        })
        sys.exit(0)
    # Headless server mode for automated smoke tests of the packaged exe:
    # FRIDAY_HEADLESS_PORT=5015 serves the Flask app over real HTTP instead of
    # opening the desktop GUI window. Normal double-click launches are unchanged.
    if os.getenv("FRIDAY_HEADLESS_PORT"):
        port = int(os.getenv("FRIDAY_HEADLESS_PORT", "5015"))
        create_app().run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
        sys.exit(0)
    run_desktop_app()
