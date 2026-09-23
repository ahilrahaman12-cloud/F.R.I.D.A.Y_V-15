"""Self-awareness: a live, grounded self-model for F.R.I.D.A.Y.

Every request can include a compact ``describe()`` in the system instruction so
the assistant answers "what time is it / what's running / how much RAM" from
real local facts instead of guessing. ``snapshot()`` returns the full picture
for the ``/api/self`` endpoint and diagnostics.
"""

from __future__ import annotations

import os
import platform
import socket
import sys
import threading
import time
from datetime import datetime
from typing import Any, Callable

import psutil

import config
from config import MODEL_NAME, OBSIDIAN_VAULT_DIR, VAULT_DIR


class SelfAwareness:
    """Maintains static identity plus per-request live state."""

    def __init__(
        self,
        memory: Any,
        observer: Any | None = None,
        model_name: str = MODEL_NAME,
        version: str = config.APP_VERSION,
    ) -> None:
        self._memory = memory
        self._observer = observer
        self._model_name = model_name
        self._version = version
        self._started_at = time.time()
        self._request_count = 0
        self._lock = threading.Lock()
        self._get_tools: Callable[[], list[str]] = lambda: []

    # ------------------------------------------------------------ identity
    def _static_identity(self) -> dict[str, Any]:
        return {
            "name": "F.R.I.D.A.Y.",
            "role": "Windows desktop assistant",
            "core_model": self._model_name,
            "app_version": self._version,
            "host_machine": platform.node(),
            "username": os.getenv("USERNAME") or os.getenv("USER") or "unknown",
            "os": f"{platform.system()} {platform.release()}",
            "python_version": sys.version.split()[0],
            "process_id": os.getpid(),
            "install_mode": "executable" if getattr(sys, "frozen", False) else "source",
            "home_dir": str(config.PROJECT_ROOT),
            "workspace_dir": str(config.WORKSPACE_DIR),
            "memory_vault_dir": str(
                self._memory.vault_dir if hasattr(self._memory, "vault_dir") else VAULT_DIR
            ),
            "obsidian_vault_configured": str(OBSIDIAN_VAULT_DIR),
        }

    # ---------------------------------------------------------- live state
    def _live_state(self) -> dict[str, Any]:
        now = datetime.now().astimezone()
        state: dict[str, Any] = {
            "local_time": now.isoformat(timespec="seconds"),
            "timezone": now.tzname() or "UTC",
            "session_uptime_seconds": int(time.time() - self._started_at),
            "request_count": self._request_count,
        }

        try:
            if sys.platform == "win32":
                import ctypes

                user32 = ctypes.windll.user32
                state["screen_resolution"] = f"{user32.GetSystemMetrics(0)}x{user32.GetSystemMetrics(1)}"
        except Exception:
            pass

        try:
            from core.tools import get_screen_context

            context = get_screen_context()
            state["visible_windows"] = context.get("windows", [])
            state["active_window"] = context.get("active_window", "")
        except Exception:
            pass

        try:
            observer = self._observer
            if observer is not None:
                status = observer.status()
                frame_age = None
                if status.get("captured_at"):
                    frame_age = round(time.time() - float(status["captured_at"]), 1)
                state["vision"] = {
                    "enabled": bool(status.get("enabled")),
                    "running": bool(status.get("running")),
                    "frame_age_seconds": frame_age,
                    "capture_interval_seconds": status.get("interval_seconds"),
                }
            else:
                state["vision"] = {"enabled": False, "running": False}
        except Exception:
            state["vision"] = {"enabled": False, "running": False}

        try:
            memory = psutil.virtual_memory()
            state["system"] = {
                "cpu_percent": round(psutil.cpu_percent(interval=None)),
                "ram_percent": round(memory.percent),
                "ram_used_gb": round(memory.used / (1024**3), 1),
                "process_count": len(psutil.pids()),
            }
        except Exception:
            pass

        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(("8.8.8.8", 80))
            state["network_ip"] = probe.getsockname()[0]
            probe.close()
        except OSError:
            state["network_ip"] = "offline"

        return state

    # -------------------------------------------------------- capabilities
    def _capabilities(self) -> list[str]:
        try:
            return sorted(self._get_tools())
        except Exception:
            return []

    # ------------------------------------------------------------ public API
    def set_tool_provider(self, provider: Callable[[], list[str]]) -> None:
        """Register the callable that lists available tool names."""
        self._get_tools = provider

    def note_request(self) -> None:
        """Count a processed request for the live snapshot."""
        with self._lock:
            self._request_count += 1

    def snapshot(self) -> dict[str, Any]:
        """Full self-model for /api/self and diagnostics."""
        return {
            "identity": self._static_identity(),
            "live_state": self._live_state(),
            "capabilities": self._capabilities(),
            "memory_summary": self._memory.memory_summary(),
        }

    def describe(self) -> str:
        """Compact self-description injected into the system instruction."""
        live = self._live_state()
        identity = self._static_identity()
        memory_line = self._memory.memory_summary()
        vision = live.get("vision", {})
        system = live.get("system", {})
        vision_note = (
            f"Vision: {'enabled' if vision.get('enabled') else 'disabled'}"
            + (
                f", newest frame {vision.get('frame_age_seconds')}s old"
                if vision.get("frame_age_seconds") is not None
                else ""
            )
        )
        lines = [
            f"You are {identity['name']}, version {identity['app_version']}, running in {identity['install_mode']} mode.",
            f"Host: {identity['host_machine']} (user {identity['username']}), {identity['os']}.",
            f"Local time: {live.get('local_time', 'unknown')} ({live.get('timezone', 'UTC')}); "
            f"session uptime {live.get('session_uptime_seconds', 0)}s; requests handled {live.get('request_count', 0)}.",
            f"Screen: {live.get('screen_resolution', 'unknown')}; active window: {live.get('active_window') or 'unknown'}.",
            vision_note,
            f"System: CPU {system.get('cpu_percent', '?')}%, RAM {system.get('ram_percent', '?')}%, "
            f"{system.get('process_count', '?')} processes.",
            f"Memory: {memory_line}.",
        ]
        return "\n".join(lines)
