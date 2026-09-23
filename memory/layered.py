"""LayeredMemory: facade composing the four memory layers.

Drop-in replacement for the previous ``MemoryStore``:

  - WorkingMemory  — bounded live conversation window (mirrored to vault)
  - SemanticIndex  — vector embeddings over vault notes for recall
  - StateStore     — SQLite key-value state that survives restarts
  - MemoryStore    — the vault (Obsidian-compatible markdown, source of truth)

Every vault write is followed by a best-effort semantic sync of that note so
recall stays current without a background indexer.
"""

from __future__ import annotations

from pathlib import Path

from config import PROJECT_ROOT, STATE_DB_PATH, VAULT_DIR, WORKING_MEMORY_MAX_CHARS, WORKING_MEMORY_MAX_TURNS
from memory.semantic import SemanticIndex
from memory.state import StateStore
from memory.store import MemoryStore
from memory.working import WorkingMemory


class LayeredMemory:
    """Composes all memory layers behind the MemoryStore API."""

    def __init__(
        self,
        vault_dir: Path | None = None,
        *,
        working_max_chars: int = WORKING_MEMORY_MAX_CHARS,
        working_max_turns: int = WORKING_MEMORY_MAX_TURNS,
        state_db_path: Path | None = None,
    ) -> None:
        self.vault = MemoryStore(vault_dir=vault_dir)
        mirror_path = self.vault.vault_dir / "Session_Window.md"
        self.session_file = mirror_path
        self.working = WorkingMemory(
            max_chars=working_max_chars,
            max_turns=working_max_turns,
            mirror_path=mirror_path,
            persist_path=self.vault.vault_dir.parent / "workspace" / "session_window.json",
        )
        self.state = StateStore(db_path=state_db_path or STATE_DB_PATH)
        self.semantic = SemanticIndex()
        # Expose the vault attributes the rest of the codebase already uses.
        self.vault_dir = self.vault.vault_dir
        self.profile_file = self.vault.profile_file
        self.notes_file = self.vault.notes_file
        self.activity_file = self.vault.activity_file
        self.sync_vault()

    # ------------------------------------------------------------ vault API
    def context(self, query: str = "") -> str:
        """Vault context plus the notes semantically closest to the query."""
        base = self.vault.context(query)
        try:
            keys = self.semantic.search(query, limit=2)
        except Exception:
            keys = []
        extra_sections = []
        for key in keys:
            path = Path(key)
            if not path.is_file() or not path.is_relative_to(self.vault.vault_dir):
                continue
            try:
                text = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if text and text not in base:
                relative = path.relative_to(self.vault.vault_dir)
                extra_sections.append(f"## Semantic match: {relative}\n{text[:3_000]}")
        return "\n\n".join([base, *extra_sections]) if extra_sections else base

    def append_preference(self, preference: str) -> None:
        self.vault.append_preference(preference)
        self._sync_file(self.vault.profile_file)

    def append_lesson(self, lesson: str) -> None:
        self.vault.append_lesson(lesson)
        self._sync_file(self.vault.notes_file)

    def log_activity(self, event: str) -> None:
        self.vault.log_activity(event)

    # ------------------------------------------------------ working memory
    def record_turn(self, speaker: str, text: str) -> None:
        """Track one live exchange in the working window."""
        self.working.add(speaker, text)

    def remember_turns(self, user_prompt: str, assistant_response: str) -> None:
        """Record a completed exchange (V14 API) in one call."""
        self.record_turn("user", user_prompt)
        self.record_turn("friday", assistant_response)

    def clear_working(self) -> None:
        self.working.clear()

    def reset_session(self) -> None:
        """V14 name for clearing the live window (alias of clear_working)."""
        self.clear_working()

    def history_contents(self, fallback: list | None = None) -> list:
        """Render the working window as structured chat history (V14).

        The last few turns are replayed to the model as proper user/assistant
        messages, giving it immediate conversational context without bloating
        the system instruction. Returns ``fallback`` untouched when this layer
        has nothing to add (plain MemoryStore has no such method, so the brain
        probes for it).
        """
        turns = self.working.turns()
        if not turns:
            return list(fallback or [])
        try:
            from google.genai import types

            history = [
                types.Content(
                    role="model" if turn.speaker == "friday" else "user",
                    parts=[types.Part.from_text(text=turn.text)],
                )
                for turn in turns
            ]
        except Exception:
            return list(fallback or [])
        # Keep the brain's own turn cap so the prompt window stays bounded.
        return history[-(self.working.max_turns):]

    # ------------------------------------------------------------ state API
    def get_state(self, key: str, default: str | None = None) -> str | None:
        return self.state.get(key, default)

    def set_state(self, key: str, value: str) -> bool:
        return self.state.set(key, value)

    # --------------------------------------------------------- maintenance
    def sync_vault(self) -> int:
        """Embed every vault note; returns the number of notes indexed."""
        synced = 0
        try:
            note_paths = list(self.vault.vault_dir.rglob("*.md"))
        except OSError:
            return synced
        for path in note_paths:
            if self._sync_file(path):
                synced += 1
        return synced

    def _sync_file(self, path: Path) -> bool:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return False
        try:
            self.semantic.sync_note(path, text)
            return True
        except Exception:
            return False

    def stats(self) -> dict:
        """Layer-by-layer numbers for the HUD MEMORY panel (/api/memory)."""
        working = self.working.stats()
        semantic = self.semantic.stats()
        try:
            vault_notes = sum(1 for _ in self.vault.vault_dir.rglob("*.md"))
        except OSError:
            vault_notes = 0
        return {
            "working_turns": working["turns"],
            "working_chars": working["chars"],
            "semantic_vectors": semantic.get("vectors", 0),
            "semantic_backend": semantic.get("backend", "-"),
            "state_keys": self.state.count(),
            "vault": self.vault.vault_dir,
            "vault_notes": vault_notes,
            "session_file": self.session_file,
        }

    def memory_summary(self) -> str:
        """Human-readable fill levels for the self-awareness snapshot."""
        working = self.working.stats()
        semantic = self.semantic.stats()
        try:
            note_count = sum(1 for _ in self.vault.vault_dir.rglob("*.md"))
        except OSError:
            note_count = 0
        return (
            f"working window {working['turns']}/{working['max_turns']} turns "
            f"({working['chars']}/{working['max_chars']} chars), "
            f"{semantic['vectors']} semantic vectors ({semantic['backend']} backend), "
            f"{self.state.count()} state keys, {note_count} vault notes"
        )

    def close(self) -> None:
        """Release database handles (used by tests)."""
        self.semantic.close()
        self.state.close()
