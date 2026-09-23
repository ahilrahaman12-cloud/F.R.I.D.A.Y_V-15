"""Background screen observer that keeps only the newest frame in memory.

Privacy model: capture is **opt-in** (off by default via config). When
disabled, any stored frame is discarded immediately and ``latest_image()``
returns ``None`` so nothing from the screen can reach the model.
"""

import threading
import time
from typing import Any

import pyautogui

from config import SCREEN_SHARE_ENABLED


class ScreenObserver:
    """Capture the desktop on an interval without writing frames to disk."""

    def __init__(self, interval_seconds: float, enabled: bool = SCREEN_SHARE_ENABLED) -> None:
        self.interval_seconds = interval_seconds
        self.enabled = enabled
        self._lock = threading.Lock()
        self._latest_image: Any | None = None
        self._captured_at: float | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if self.enabled:
            self.capture_once()
        self._thread = threading.Thread(target=self._run, name="friday-screen-observer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def set_enabled(self, enabled: bool) -> None:
        """Toggle capture at runtime; disabling drops any stored frame now."""
        with self._lock:
            self.enabled = enabled
            self._latest_image = None
            self._captured_at = None

    def capture_once(self) -> None:
        # Off means off: do not even grab the screen. The enabled check runs
        # again after capture in case the toggle flipped mid-screenshot.
        with self._lock:
            if not self.enabled:
                return
        try:
            image = pyautogui.screenshot()
        except Exception:
            return
        with self._lock:
            if not self.enabled:
                return
            self._latest_image = image
            self._captured_at = time.time()

    def latest_image(self) -> Any | None:
        with self._lock:
            if not self.enabled:
                return None
            return self._latest_image.copy() if self._latest_image is not None else None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": bool(self._thread and self._thread.is_alive()),
                "enabled": self.enabled,
                "captured_at": self._captured_at,
                "interval_seconds": self.interval_seconds,
            }

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            if not self.enabled:
                continue
            self.capture_once()
