"""Obsidian-compatible Markdown memory store."""

from datetime import datetime
from pathlib import Path
import os
import re
import threading

from config import OBSIDIAN_VAULT_DIR, VAULT_DIR

_DEFAULT_VAULT_FALLBACK = VAULT_DIR


class MemoryStore:
    """Loads user preferences and operating notes from local markdown files."""

    _MAX_SECTION_CHARS = 8_000  # per-file cap injected into prompts
    _MAX_ENTRIES = 200  # safety cap so files cannot grow without bound

    def __init__(self, vault_dir: Path | None = None) -> None:
        requested = vault_dir or OBSIDIAN_VAULT_DIR
        try:
            requested.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Obsidian path may live on a removable/unmounted drive; degrade
            # gracefully to the project-local vault instead of crashing.
            requested = _DEFAULT_VAULT_FALLBACK
            requested.mkdir(parents=True, exist_ok=True)
        self.vault_dir = requested
        self._lock = threading.RLock()
        self.profile_file = self.vault_dir / "User_Profile.md"
        self.notes_file = self.vault_dir / "System_Lessons.md"
        self.activity_file = self.vault_dir / "Activity_Log.md"
        self._ensure_file(self.profile_file, "# User Profile\n")
        self._ensure_file(self.notes_file, "# Operating Notes\n")
        self._ensure_file(self.activity_file, "# F.R.I.D.A.Y. Activity Log\n")

    @staticmethod
    def _ensure_file(path: Path, heading: str) -> None:
        if not path.exists():
            try:
                path.write_text(heading, encoding="utf-8")
            except OSError:
                pass

    def context(self, query: str = "") -> str:
        """Return core memory plus the notes most relevant to the current task."""
        sections = []
        with self._lock:
            for label, path in (("User preferences", self.profile_file), ("Operating notes", self.notes_file)):
                text = self._read(path)
                if text:
                    sections.append(f"## {label}\n{text[-self._MAX_SECTION_CHARS:]}")

            note_paths = [
                path for path in self.vault_dir.rglob("*.md")
                if path not in {self.profile_file, self.notes_file, self.activity_file}
            ]
            keywords = {word.lower() for word in re.findall(r"[A-Za-z0-9_]{3,}", query)}
            ranked_notes = []
            for path in note_paths:
                text = self._read(path)
                searchable = f"{path.name}\n{text}".lower()
                score = sum(keyword in searchable for keyword in keywords)
                if score:
                    ranked_notes.append((score, path, text))
            for _, path, text in sorted(ranked_notes, key=lambda item: (-item[0], item[1].name))[:4]:
                sections.append(f"## Linked note: {path.relative_to(self.vault_dir)}\n{text[:3_000]}")
        return "\n\n".join(sections) or "No saved memory is available."

    def append_preference(self, preference: str) -> None:
        """Persist one explicit user preference, skipping exact duplicates."""
        self._append_markdown(self.profile_file, preference)

    def append_lesson(self, lesson: str) -> None:
        """Persist one concise operating correction, skipping exact duplicates."""
        self._append_markdown(self.notes_file, lesson)

    def log_activity(self, event: str) -> None:
        """Append a timestamped activity entry visible in Obsidian."""
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._lock, self.activity_file.open("a", encoding="utf-8") as activity:
            activity.write(f"\n- [{timestamp}] {event.strip()}\n")
        self._trim_file(self.activity_file, keep_tail=500)

    def _append_markdown(self, path: Path, text: str) -> None:
        text = text.strip()
        if not text:
            return
        with self._lock:
            if self._contains_line(path, text):
                return
            with path.open("a", encoding="utf-8") as file:
                file.write(f"\n- {text}\n")
            self._trim_file(path)

    @staticmethod
    def _contains_line(path: Path, text: str) -> bool:
        needle = f"- {text}"
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip() == needle.strip():
                    return True
        except OSError:
            return False
        return False

    @classmethod
    def _trim_file(cls, path: Path, keep_tail: int = _MAX_ENTRIES) -> None:
        """Keep markdown list files from growing without bound."""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        heading = lines[0] if lines else ""
        entries = [line for line in lines[1:] if line.strip()]
        if len(entries) <= keep_tail:
            return
        kept = entries[-keep_tail:]
        try:
            path.write_text(f"{heading}\n\n" + "\n".join(kept) + "\n", encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
