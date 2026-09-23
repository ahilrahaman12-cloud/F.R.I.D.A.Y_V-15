"""Working memory: the live conversation window for the current session.

Volatile by design — it holds only recent turns so prompts stay small and
relevant, and it mirrors a bounded transcript into the vault as
``Session_Window.md`` so an Obsidian user can see the live session.

V14 addition: the window is persisted to a small JSON snapshot on every turn
and reloaded on launch, so the conversation survives restarts (RESET SESSION
clears it again).
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from config import WORKING_MEMORY_MAX_CHARS, WORKING_MEMORY_MAX_TURNS


@dataclass
class WorkingTurn:
    """One conversational exchange, used verbatim in prompts."""

    speaker: str  # "user" or "friday"
    text: str
    timestamp: float = field(default_factory=time.time)

    @property
    def role(self) -> str:
        """Chat-history role for the model API: "user" or "assistant"."""
        return "user" if self.speaker == "user" else "assistant"

    @property
    def at(self) -> str:
        """Human-readable timestamp for the vault mirror."""
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp))


class WorkingMemory:
    """Bounded, thread-safe buffer of recent conversation turns."""

    def __init__(
        self,
        max_chars: int = WORKING_MEMORY_MAX_CHARS,
        max_turns: int = WORKING_MEMORY_MAX_TURNS,
        mirror_path: Path | None = None,
        persist_path: Path | None = None,
    ) -> None:
        self.max_chars = max_chars
        self.max_turns = max_turns
        self._turns: list[WorkingTurn] = []
        self._lock = threading.RLock()
        self._mirror_path = mirror_path
        self._persist_path = persist_path
        if persist_path is not None:
            self.load()

    # ------------------------------------------------------------ recording
    def add(self, speaker: str, text: str) -> None:
        """Record one turn, trim to bounds, mirror, and persist."""
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            self._turns.append(WorkingTurn(speaker=speaker, text=text))
            self._trim_locked()
        self._mirror()
        self.save()

    def turns(self) -> list[WorkingTurn]:
        with self._lock:
            return list(self._turns)

    def clear(self) -> None:
        """Empty the window, its mirror note, and the persisted snapshot."""
        with self._lock:
            self._turns.clear()
        self._mirror()
        if self._persist_path is not None:
            try:
                self._persist_path.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------- rendering
    def window_text(self) -> str:
        """Render the current window as a compact transcript for prompts."""
        with self._lock:
            lines = [
                f"{turn.speaker}: {turn.text}"
                for turn in self._turns
            ]
        return "\n".join(lines)

    def stats(self) -> dict[str, int]:
        """Fill-level summary for the self-awareness snapshot."""
        with self._lock:
            chars = sum(len(turn.text) for turn in self._turns)
            return {"turns": len(self._turns), "chars": chars, "max_turns": self.max_turns, "max_chars": self.max_chars}

    def char_count(self) -> int:
        with self._lock:
            return sum(len(turn.text) for turn in self._turns)

    def is_empty(self) -> bool:
        with self._lock:
            return not self._turns

    # ------------------------------------------------- session persistence
    def snapshot(self) -> list[dict]:
        """Plain-data copy of the window for persistence."""
        with self._lock:
            return [
                {"speaker": turn.speaker, "text": turn.text, "timestamp": turn.timestamp}
                for turn in self._turns
            ]

    def restore(self, items: list[dict] | None) -> None:
        """Replace the window with persisted turns (bounds re-applied)."""
        restored: list[WorkingTurn] = []
        for item in items or []:
            try:
                restored.append(
                    WorkingTurn(
                        speaker=str(item.get("speaker", "user")),
                        text=str(item.get("text", "")),
                        timestamp=float(item.get("timestamp", time.time())),
                    )
                )
            except (AttributeError, TypeError, ValueError):
                continue
        with self._lock:
            self._turns = restored
            self._trim_locked()

    def save(self) -> None:
        """Persist the window to disk; never raises (persistence is best-effort)."""
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._persist_path.write_text(
                json.dumps(self.snapshot(), ensure_ascii=False), encoding="utf-8"
            )
        except (OSError, TypeError, ValueError):
            pass

    def load(self) -> bool:
        """Reload the persisted window. True when turns were restored."""
        if self._persist_path is None:
            return False
        try:
            raw = self._persist_path.read_text(encoding="utf-8")
            items = json.loads(raw)
        except (OSError, ValueError):
            return False
        if not isinstance(items, list):
            return False
        self.restore(items)
        return not self.is_empty()

    # --------------------------------------------------------------- internals
    def _trim_locked(self) -> None:
        """Keep the newest turns within both the count and character budgets."""
        while len(self._turns) > self.max_turns:
            self._turns.pop(0)
        while self._turns and sum(len(turn.text) for turn in self._turns) > self.max_chars:
            self._turns.pop(0)

    def _mirror(self) -> None:
        """Best-effort copy of the live window into the vault (Obsidian)."""
        if self._mirror_path is None:
            return
        try:
            self._mirror_path.parent.mkdir(parents=True, exist_ok=True)
            body = self.window_text() or "(empty)"
            self._mirror_path.write_text(
                f"# Session Window\n\nLive conversation mirror — {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"{body}\n",
                encoding="utf-8",
            )
        except OSError:
            pass
