# F.R.I.D.A.Y. — Gemini-powered desktop assistant

A Windows desktop assistant with a sci-fi HUD: it watches your screen, remembers
your preferences in an Obsidian-compatible vault, and controls the desktop
through a gated tool layer (mouse, keyboard, windows, apps, files, browser).

Ships as a **standalone executable** — no Python or terminal window required —
that asks for your Gemini API key on first run and remembers it.

## What's new in this upgrade

- **Standalone windowed executable**: built with PyInstaller (`icon.ico`
  embedded, no console flash). Mutable state (`.env`, `workspace/`, `vault/`,
  `links.json`) lives next to the exe, never in temp folders.
- **First-run setup page**: the executable gates the UI behind an
  "API KEY REQUIRED" screen; the key is validated, saved to a local `.env`,
  and remembered for every future launch.
- **Two-layer safety gate**: risky *prompts* still require approval, and risky
  *tools* (delete, close app, hotkeys, desktop writes) now require approval even
  when the prompt looked safe. The UI shows an APPROVE / DENY bar.
- **Voice in, voice out**: the mic button records real audio, Gemini transcribes
  it, and replies are spoken back via Gemini TTS.
- **New tools**: `open_url` (http/https only) and `get_screen_size` so clicks
  stay on-screen; mouse coordinates are clamped to the display.
- **Safer process control**: `close_application` refuses to terminate critical
  system processes (explorer, csrss, svchost, ...) or itself.
- **Real GPU telemetry**: NVML (NVIDIA) with a Windows-counter fallback feeds
  the previously decorative GPU gauge.- **Modular frontend with a strict CSP**: the HUD is no longer a monolithic HTML file — styles and scripts live in `static/css/` and `static/js/`, third-party libraries (three.js r128, MediaPipe hands + models) are **vendored locally** in `static/vendor/` so the app works fully offline with no CDN or supply-chain exposure, and every page ships a `Content-Security-Policy` (no inline scripts, no remote code).
- **Single persistent event loop**: all async brain work runs on one dedicated background asyncio loop instead of a fresh `asyncio.run()` per request, and a turn lock serializes multi-step tool tasks, fixing a thread-safety hole under Flask's threaded server.
- **Per-request turn state**: chat session, step log, and prompt travel on a per-request turn object, so a finished turn can never leak context into the next one; a mid-task `RESET SESSION` also invalidates the in-flight session instead of resuming it.
- **Broader destructive-prompt gate**: the approval regex now also catches erase/wipe/purge/uninstall, reboot, log off, uploads/publishing, and kill/force-quit phrasing — while benign prompts ("check my email", "open figma") stay ungated.
- **Hardened responses**: `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer` on every response; pinned dependency versions in `requirements.txt` for reproducible exe builds. Unexpected 500s return a generic message — full details go to a rotating `friday.log` next to the app (vital for the windowed exe, which has no console).
- **Production observability**: `/api/health` reports the app version (`checks.version`, single source of truth in `config.APP_VERSION`, kept in sync with the installer via a regression test); the installer's Apps & Features entry reports the real installed size.
- **Resilient memory**: duplicate entries are skipped, files are trimmed, and a missing/unmounted Obsidian vault falls back to the local `vault/` folder.
- **Per-request action log** (`steps` in the API response), tool errors are
  isolated so one failure can't kill a task, and a RESET SESSION button clears
  conversation state via `POST /api/reset`.
- **Restored from the original monolith, rebuilt safely**: master volume control
  (`set_volume`, `adjust_volume`, `toggle_mute` via pycaw), media keys
  (`press_media_key`), Spotify/YouTube playback search, named link shortcuts
  (`save_custom_link` / `open_custom_link`, stored in `links.json`),
  `lock_workstation`, and `shutdown_computer` with cancel support. Shutdown and
  volume changes are approval-gated; the schedule uses a delay so it can be
  cancelled. The `/office` page (OFFICE button in the HUD) manages link tiles.

## Run from source

1. Create a virtual environment and install `requirements.txt`.
2. Copy `.env.example` to `.env`, then insert your own Gemini API key.
   Both Google key formats are accepted: new keys starting with `AQ.` and
   classic `AIza` keys. `AQ.` keys can be bound to the Gemini API or to Vertex
   AI express mode; if the first request fails with a key-auth error the app
   automatically retries once against the other surface (or force one with
   `GEMINI_BACKEND=vertex` in `.env`).
3. Run `python app.py`.

## Build the executable

One command builds and signs everything (Windows):

```bat
build.bat                REM app exes + installers, then sign all of dist\*.exe
build.bat --no-installers REM app exes only, then sign
build.bat --selftest     REM ...and smoke-test the signed portable exe
```

The script reuses the venv, runs `friday.spec`, builds both installers, and
signs every `dist\*.exe` with the self-signed code-signing certificate
(`build/sign_installers.ps1`: per-user trust + DigiCert timestamp; public key
exported to `build/friday-signing.cer` for verifying on other machines).

Manual equivalent:

```bash
.venv/Scripts/python.exe -m pip install pyinstaller
.venv/Scripts/python.exe -m PyInstaller friday.spec --noconfirm
.venv/Scripts/python.exe build/build_installers.py
powershell -NoProfile -ExecutionPolicy Bypass -File build/sign_installers.ps1
```

This produces these executables in `dist/`:

| Output | Behavior |
| --- | --- |
| `dist/friday.exe` | Asks for the Gemini API key on first run |
| `dist/friday-embedded.exe` | Carries a precompiled key (`build/rthook_embedded.py`) |
| `dist/friday-installer.exe` | Installer wrapping the portable exe |
| `dist/friday-installer-embedded.exe` | Installer wrapping the embedded exe |

The build is windowed (`console=False`), reads an optional `.env` from its own
folder, and creates `workspace/`, `vault/`, and `links.json` next to itself on
demand. A hidden self-test exists for verifying the packaged exe without
opening the GUI:

```bash
FRIDAY_SELFTEST=1 ./friday.exe
```

## First-run setup (portable build)

1. Launch `friday.exe`. The window opens on an **API KEY REQUIRED** screen.
2. Paste your key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
3. Click **Initialize System** — the key is validated and written to `.env`
   next to the exe, then the main HUD loads. Subsequent launches skip setup.

To move the app to another machine, copy `friday.exe` together with its
`.env` — or copy the exe alone and repeat the setup there.

## Project layout

```
app.py            Flask app, routes, security headers, event-loop bridge
config.py         Env/model/key configuration, .env persistence
core/brain.py     Conversation + tool loop, approval gates, TTS/STT
core/tools.py     Tool functions + declarations exposed to Gemini
computer/         Desktop control layer (mouse, keyboard, windows, audio)
memory/           Obsidian-compatible vault store
vision/           Screen observer (periodic local frames)
system/           CPU/RAM/GPU telemetry
templates/        Slim HTML shells (CSP-protected)
static/css/       Styles extracted per page
static/js/        boot / scene / waveform / voice / app scripts
static/vendor/    Vendored three.js + MediaPipe assets (offline, no CDN)
tests/            Route, brain, memory, tools, and setup test suites
```

## Test it

Run `python -m unittest discover -s tests -v` from this folder. The suite
covers routes, brain gating, memory, tools, and the first-run setup flow —
no API key needed.

## Boot screen

Both pages run a cinematic initialization overlay that probes `GET /api/health`
instead of faking success. Diagnostics show the configured model, memory vault
state, screen-observer mode, and telemetry status as they resolve. A healthy
system flashes **SYSTEM ONLINE**; the portable build without a key reports
**NEEDS_API_KEY**, a misconfigured source install shows **DEGRADED MODE**, and
an offline server shows **OFFLINE** in amber, holding longer so you can read it.

## Troubleshooting

- **401 `ACCESS_TOKEN_TYPE_UNSUPPORTED` on chat** — the key is the wrong
  credential type (e.g. an OAuth token, not an AI Studio API key) or is
  API-restricted. Create a fresh key at
  [aistudio.google.com/apikey](https://aistudio.google.com/apikey), then update
  `.env` (source install) or delete the `.env` next to the exe and re-run the
  setup page.
- **Vault reports `missing`/`fallback`** — `OBSIDIAN_VAULT_PATH` points to an
  unavailable drive; the app falls back to the local `vault/` automatically.
- **PyInstaller warns about a missing hidden import** — verify it against the
  runtime behavior; optional platform imports (e.g. `nvidia_ml_py` on machines
  without NVML) degrade gracefully at run time.

## Privacy model

**Default: nothing beyond your typed prompt leaves this machine.**

| Data | Where it goes | Default |
| --- | --- | --- |
| Your typed prompt + tool results | Google Gemini (required to answer) | always |
| Screen frames | Google Gemini | **OFF** — opt-in |
| Conversation content (memory extraction) | Google Gemini | **OFF** — opt-in |
| Memory / preferences | Local Markdown vault only | always local |
| Activity log | Local vault only; records *that* a request ran, never its text | always local |
| API key | Local `.env` next to the app | always local |

Opt in/out anytime:

- **In the app:** `POST /api/privacy {"screen_share": true}` or `{"memory_learning": true}` (persisted to `.env`, applied immediately).
- **In `.env`:** `FRIDAY_SCREEN_SHARE=1` sends a periodic screenshot with each request (frames live in RAM only, never on disk). `FRIDAY_MEMORY_LEARNING=1` lets Gemini extract durable preferences into the local vault.

When screen sharing is off, the app never even grabs the screen; the assistant relies on tool results (`get_screen_context`, `get_screen_size`) and your description instead.

**Warning on the embedded build:** `friday-embedded.exe` / `friday-installer-embedded.exe` contain your compiled-in API key and must only be distributed to people you trust with that key. The portable installer asks each user for their own key and ships no secret. Never commit or zip `build/rthook_embedded.py` or `.env`.

## Screen capture (when enabled)

With screen sharing on, a new local frame is captured every two seconds and held in memory only; the latest frame is sent to Gemini with each request so F.R.I.D.A.Y. can visually understand the desktop.

## Obsidian Memory

Open your vault folder (set via `OBSIDIAN_VAULT_PATH`, defaulting to the
project-local `vault/`) in Obsidian. F.R.I.D.A.Y. updates its profile, operating
lessons, and activity log there in the background. Add your own Markdown notes
to that vault; notes whose filename or contents match the current request are
included as context automatically.

## API surface

| Route | Purpose |
| --- | --- |
| `POST /api/chat` | Send a prompt; returns status, response, steps |
| `POST /api/confirm` | Approve/deny a prompt-gated request |
| `POST /api/confirm/tools` | Approve/deny gated tool calls mid-task |
| `POST /api/reset` | Clear conversation history and pending state |
| `POST /api/transcribe` | multipart `audio` file → Gemini transcription |
| `POST /api/speak` | `{text}` → base64 PCM audio via Gemini TTS |
| `GET /api/stats` | CPU / RAM / GPU / disk / network telemetry |
| `GET /api/health` | Component health for the boot screens (Gemini key, vault, observer, telemetry) |
| `GET /setup` | First-run API-key setup page (portable build) |
| `GET /api/setup/status` | Setup state: `needs_setup`, `key_source`, overall status |
| `POST /api/setup/key` | Validate and save the Gemini key to the local `.env` |
| `GET /office` | Link-tile dashboard (office dock) |
| `GET /api/links` | List saved link shortcuts |
| `POST /api/links/save` | Save a link shortcut `{name, url}` |
| `POST /api/links/open` | Open a saved link `{name}` |
