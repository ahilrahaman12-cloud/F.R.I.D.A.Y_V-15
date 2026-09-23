"""SemanticIndex: vector embeddings over the markdown vault for semantic recall.

Dual embedding backends:
  - ``gemini``  — Google Gemini embedding API (opt-in; note text leaves the
                  machine only when EMBEDDING_BACKEND=gemini).
  - ``hash``    — fully local deterministic fallback (token hashing).

Gemini vectors are 3072-dim L2-normalized; hash vectors are 256-dim
L2-normalized. The two are not comparable, so the index records which backend
produced each vector and rebuilds when the backend changes.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import time
from pathlib import Path

from config import EMBEDDING_BACKEND, SEMANTIC_DB_PATH, get_api_key

_HASH_DIMS = 256
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
_MAX_SYNC_CHARS_PER_NOTE = 20_000


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def hash_embedding(text: str) -> list[float]:
    """Deterministic local embedding: bag-of-words hashed into fixed dims."""
    vector = [0.0] * _HASH_DIMS
    tokens = _tokenize(text)
    if not tokens:
        return vector
    for token in tokens:
        digest = hash(token)
        index = digest % _HASH_DIMS
        sign = 1.0 if (digest >> 8) & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class _HashEmbedder:
    """Fallback backend: local, offline, zero dependencies."""

    backend_name = "hash"
    dims = _HASH_DIMS

    @staticmethod
    def embed(text: str) -> list[float]:
        return hash_embedding(text)


class GeminiEmbedder:
    """Gemini embedding API backend (requires a Gemini key)."""

    backend_name = "gemini"
    dims = 3072  # gemini-embedding-001 output dimensionality
    MODEL = "gemini-embedding-001"

    def __init__(self) -> None:
        from config import build_genai_client

        self._client = build_genai_client(get_api_key())

    def embed(self, text: str) -> list[float]:
        result = self._client.models.embed_content(model=self.MODEL, contents=text[: _MAX_SYNC_CHARS_PER_NOTE])
        return [float(value) for value in result.embeddings[0].values]


def _make_embedder(backend: str):
    """Return an embedder for the requested backend, degrading to hash."""
    if backend == "gemini":
        try:
            return GeminiEmbedder()
        except Exception:
            return _HashEmbedder()
    return _HashEmbedder()


class SemanticIndex:
    """SQLite-backed vector store over vault notes; synced after vault writes."""

    def __init__(self, db_path: Path | None = None, backend: str = EMBEDDING_BACKEND) -> None:
        self.db_path = db_path or SEMANTIC_DB_PATH
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS vectors ("
                " path TEXT PRIMARY KEY,"
                " backend TEXT NOT NULL,"
                " vector TEXT NOT NULL,"
                " synced_at TEXT NOT NULL)"
            )
            self._conn.commit()
        self._embedder = _make_embedder(backend)
        self._vectors: dict[str, tuple[str, list[float]]] = {}
        self._load_vectors()

    # ------------------------------------------------------------ internals
    def _load_vectors(self) -> None:
        with self._lock:
            rows = self._conn.execute("SELECT path, backend, vector FROM vectors").fetchall()
        self._vectors = {str(row[0]): (str(row[1]), json.loads(row[2])) for row in rows}

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if len(a) != len(b) or not a:
            return 0.0
        return sum(x * y for x, y in zip(a, b))

    def _store(self, path: str, vector: list[float]) -> None:
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            self._conn.execute(
                "INSERT INTO vectors (path, backend, vector, synced_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET backend = excluded.backend, vector = excluded.vector,"
                " synced_at = excluded.synced_at",
                (path, self._embedder.backend_name, json.dumps(vector), stamp),
            )
            self._conn.commit()

    # ------------------------------------------------------------ public API
    def sync_note(self, path: Path, text: str) -> None:
        """Embed one vault note; silently skips when the backend is offline."""
        key = str(path)
        text = (text or "")[:_MAX_SYNC_CHARS_PER_NOTE]
        if not text.strip():
            self.remove(path)
            return
        try:
            vector = self._embedder.embed(text)
        except Exception:
            return
        self._store(key, vector)
        with self._lock:
            self._vectors[key] = (self._embedder.backend_name, vector)

    def remove(self, path: Path) -> None:
        key = str(path)
        with self._lock:
            self._conn.execute("DELETE FROM vectors WHERE path = ?", (key,))
            self._conn.commit()
            self._vectors.pop(key, None)

    def search(self, query: str, limit: int = 4) -> list[str]:
        """Return vault-note keys ranked by cosine similarity to the query."""
        try:
            query_vector = self._embedder.embed(query)
        except Exception:
            return []
        with self._lock:
            candidates = list(self._vectors.items())
        scored = []
        for key, (backend, vector) in candidates:
            if backend != self._embedder.backend_name:
                continue
            score = self._cosine(query_vector, vector)
            if score > 0:
                scored.append((score, key))
        scored.sort(reverse=True)
        return [key for _, key in scored[:limit]]

    def stats(self) -> dict[str, int | str]:
        with self._lock:
            backends = {backend for backend, _ in self._vectors.values()}
        return {
            "vectors": len(self._vectors),
            "backend": self._embedder.backend_name,
            "stored_backends": ",".join(sorted(backends)) or "-",
        }

    def count(self) -> int:
        with self._lock:
            return len(self._vectors)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
