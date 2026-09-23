"""StateStore: persistent SQLite key-value store for restart-surviving state.

Stores configuration and application state that must come back verbatim after
a restart — system settings, toggle positions, counters. Keys are namespaced
by convention (e.g. ``system/prefers_voice``) so layers don't collide.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from config import STATE_DB_PATH


class StateStore:
    """Thread-safe, process-safe SQLite key-value database."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or STATE_DB_PATH
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            self._conn.commit()

    def get(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return default if row is None else str(row[0])

    def set(self, key: str, value: str) -> bool:
        """Upsert one key; returns False if persistence failed (non-fatal)."""
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO state (key, value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                    (key, str(value), stamp),
                )
                self._conn.commit()
                return True
        except sqlite3.Error:
            return False

    def delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM state WHERE key = ?", (key,))
            self._conn.commit()

    def keys(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT key FROM state ORDER BY key").fetchall()
        return [str(row[0]) for row in rows]

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM state").fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
