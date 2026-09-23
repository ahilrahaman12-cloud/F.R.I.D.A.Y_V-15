"""Application configuration loaded from environment variables."""

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv


# When frozen by PyInstaller, bundled read-only data files live in the
# _MEIPASS bundle dir (extracted temp dir for onefile, _internal for onedir).
# Mutable state (.env, workspace/, vault/) needs a writable location: the exe
# folder works for the Windows portable build, but an AppImage mount is
# read-only, so when FRIDAY_STATE_DIR is set (by the Linux AppRun) or the exe
# folder is not writable, state moves to ~/.local/share/FRIDAY instead.
if getattr(sys, "frozen", False):
    exe_dir = Path(sys.executable).resolve().parent
    state_root = Path(os.getenv("FRIDAY_STATE_DIR", "")).expanduser() if os.getenv("FRIDAY_STATE_DIR") else None
    if state_root is None:
        try:
            probe = exe_dir / ".friday-write-test"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
            state_root = exe_dir
        except OSError:
            state_root = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "FRIDAY"
    if state_root.name:
        try:
            state_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    PROJECT_ROOT = state_root
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
else:
    PROJECT_ROOT = Path(__file__).resolve().parent
    BUNDLE_DIR = PROJECT_ROOT

# Load .env before reading any environment variables below.
load_dotenv(PROJECT_ROOT / ".env")

WORKSPACE_DIR = PROJECT_ROOT / "workspace"
VAULT_DIR = PROJECT_ROOT / "vault"
LINKS_FILE = PROJECT_ROOT / "links.json"
OBSIDIAN_VAULT_DIR = Path(
    os.getenv("OBSIDIAN_VAULT_PATH", r"D:\Obsedian\F.R.I.D.A.Y. Vault")
).expanduser()

# Google retired gemini-2.5-flash for new users (404 "no longer available");
# 3.6-flash is the current recommended successor for the Gemini API.
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()

# Single source of truth for the app version, reported by /api/health and
# shown on the boot screens. build/installer_app.py must keep APP_VERSION in
# sync (enforced by tests/test_installer.py).
APP_VERSION = "14.0.0"

# ---------------------------------------------------------------
# Privacy switches — both default OFF so nothing beyond the chat
# prompt itself leaves the machine unless the user asks for it.
#   FRIDAY_SCREEN_SHARE=1  send periodic screen frames with requests
#   FRIDAY_MEMORY_LEARNING=1  let Gemini extract memory from turns
# ---------------------------------------------------------------
SCREEN_SHARE_ENABLED = os.getenv("FRIDAY_SCREEN_SHARE", "0") == "1"
MEMORY_LEARNING_ENABLED = os.getenv("FRIDAY_MEMORY_LEARNING", "0") == "1"
SCREEN_OBSERVER_INTERVAL_SECONDS = max(0.5, float(os.getenv("SCREEN_OBSERVER_INTERVAL_SECONDS", "2")))

# ---------------------------------------------------------------
# Layered memory (V14): bounded working window, SQLite state that
# must survive restarts verbatim, and a semantic index over the
# vault. All mutable databases live under the writable state root.
# ---------------------------------------------------------------
DATA_DIR = PROJECT_ROOT / "data"
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
SEMANTIC_DB_PATH = DATA_DIR / "semantic_index.sqlite3"
STATE_DB_PATH = DATA_DIR / "state.sqlite3"
WORKING_MEMORY_MAX_CHARS = max(1_000, int(os.getenv("WORKING_MEMORY_MAX_CHARS", "6_000")))
WORKING_MEMORY_MAX_TURNS = max(2, int(os.getenv("WORKING_MEMORY_MAX_TURNS", "12")))

# Embedding backend for semantic recall: "gemini" uses the Gemini
# embedding API (opt-in, sends note text to Google); "hash" is a
# fully local deterministic fallback. The semantic layer falls back
# to hash automatically when the Gemini backend is unavailable.
EMBEDDING_BACKEND = (os.getenv("EMBEDDING_BACKEND", "hash").strip().lower() or "hash")

# Voice output (V14): Deepgram Aura TTS is the primary, low-latency streaming
# path; Gemini TTS is the in-app fallback; the browser's Web Speech API is the
# last resort. All optional.
# Default voice: Stella. aura-2-stella-en is only accepted by accounts with
# Aura-2 enabled; aura-stella-en works on all Aura accounts.
DEEPGRAM_TTS_MODEL = os.getenv("DEEPGRAM_TTS_MODEL", "aura-stella-en").strip() or "aura-stella-en"

# ---------------------------------------------------------------
# Voice output (V14): Deepgram Aura TTS is the primary, low-latency
# streaming path; Gemini TTS is the in-app fallback; the browser's
# Web Speech API is the last resort. All optional.
# ---------------------------------------------------------------
DEEPGRAM_TTS_MODEL = os.getenv("DEEPGRAM_TTS_MODEL", "aura-2-stella-en").strip() or "aura-2-stella-en"


def has_deepgram() -> bool:
    """True when a Deepgram API key is configured (read live from env)."""
    return bool(os.getenv("DEEPGRAM_API_KEY", "").strip())

# Google now issues new-format keys ("AQ.\u2026") for both the Gemini API and
# Vertex AI express mode; the prefix no longer identifies the surface. Default
# to the classic Gemini API host; "vertex" targets the Vertex AI express host
# instead. The brain falls back to the other surface once if a key-auth error
# shows the key belongs to the other one.
VALID_BACKENDS = ("gemini", "vertex")


def _normalize_backend(value: str | None) -> str:
    text = (value or "").strip().lower()
    if text in {"vertex", "vertexai", "aiplatform", "express"}:
        return "vertex"
    return "gemini"


def _env_backend() -> str:
    return _normalize_backend(os.getenv("GEMINI_BACKEND"))


def build_genai_client(api_key: str, backend: str | None = None):
    """Create a google-genai Client for the requested surface.

    backend: "gemini" (default, generativelanguage host) or "vertex"
    (Vertex AI express mode, aiplatform host). None reads GEMINI_BACKEND.
    """
    from google import genai

    surface = _env_backend() if backend is None else _normalize_backend(backend)
    if surface == "vertex":
        return genai.Client(vertexai=True, api_key=api_key)
    return genai.Client(api_key=api_key)


# Populated at build time for the embedded-key executable via a PyInstaller
# runtime hook (see friday.spec). The portable build leaves this empty.
_EMBEDDED_API_KEY = os.environ.pop("FRIDAY_EMBEDDED_KEY", "")
os.environ.pop("FRIDAY_EMBEDDED_KEY", None)


def has_deepgram() -> bool:
    """True when a Deepgram API key is configured (read live from env)."""
    return bool(os.getenv("DEEPGRAM_API_KEY", "").strip())


def deepgram_api_key() -> str:
    """Return the configured Deepgram TTS key (may be empty)."""
    return os.getenv("DEEPGRAM_API_KEY", "").strip()


def key_source() -> str:
    """Return where the Gemini key comes from: 'env', 'embedded', or 'none'."""
    if os.getenv("GEMINI_API_KEY", "").strip():
        return "env"
    if _EMBEDDED_API_KEY.strip():
        return "embedded"
    return "none"


def has_api_key() -> bool:
    """True when a Gemini key is available from any source."""
    return key_source() != "none"


def get_api_key() -> str:
    """Return the configured Gemini API key or raise a clear setup error."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        api_key = _EMBEDDED_API_KEY.strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key, or open /setup.")
    return api_key


def _upsert_env_line(env_path: Path, key: str, line: str) -> bool:
    """Replace the line for KEY in a .env file, or append it; True on success."""
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    except OSError:
        lines = []
    replaced = False
    prefix = f"{key}="
    for index, existing in enumerate(lines):
        if existing.strip().startswith(prefix):
            lines[index] = line
            replaced = True
            break
    if not replaced:
        lines.append(line)
    try:
        env_path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def set_env_value(key: str, value: str) -> bool:
    """Persist KEY=value into the local .env and the live environment.

    Used for the privacy switches so a UI toggle survives restarts. Values are
    restricted to safe token characters.
    """
    value = str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", value):
        return False
    if not _upsert_env_line(PROJECT_ROOT / ".env", key, f"{key}={value}"):
        return False
    os.environ[key] = value
    return True


def save_api_key_to_env(api_key: str) -> bool:
    """Persist GEMINI_API_KEY into the .env next to the app; True on success."""
    key = (api_key or "").strip()
    # Google AI Studio keys are long alphanumeric strings (may contain -, _
    # and, in newer key formats, a dot separator like "AQ.").
    if len(key) < 20 or not re.fullmatch(r"[A-Za-z0-9_.\-]+", key):
        return False
    if not _upsert_env_line(PROJECT_ROOT / ".env", "GEMINI_API_KEY", f"GEMINI_API_KEY={key}"):
        return False
    os.environ["GEMINI_API_KEY"] = key
    return True
