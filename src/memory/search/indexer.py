from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src.core.constants import ALLOWED_MEMORY_EXTENSIONS
from src.memory.assets import AssetRegistry

CHUNK_TARGET_CHARS = 1_000
SNIPPET_TOKENS = 40


@dataclass(frozen=True)
class SearchHit:
    asset_id: str
    file_name: str
    snippet: str
    score: float


class MemoryIndex:
    """Full-text search over asset markdown memory.

    SQLite FTS5 (stdlib, zero dependencies). The index is a disposable
    cache: it refreshes incrementally by content hash before each search
    and can be deleted at any time — markdown remains the source of truth.
    """

    def __init__(
        self,
        db_path: Path,
        asset_registry: AssetRegistry,
        global_runs_dir: Path | None = None,
    ) -> None:
        self.db_path = db_path
        self.asset_registry = asset_registry
        self.global_runs_dir = global_runs_dir
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # The connection is created once at startup but used from per-request
        # worker threads (serialized by the caller, e.g. the chat lock).
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._fts_available = self._init_schema()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------

    def refresh(self) -> int:
        """Sync the index with disk. Returns number of files (re)indexed."""
        cur = self._conn.cursor()
        seen: set[tuple[str, str]] = set()
        reindexed = 0
        scopes: list[tuple[str, Path]] = [
            (asset_id, self.asset_registry.resolve_asset_dir(asset_id))
            for asset_id in self.asset_registry.list_asset_ids()
        ]
        if self.global_runs_dir is not None and self.global_runs_dir.exists():
            scopes.append(("__runs__", self.global_runs_dir))
        for asset_id, scope_dir in scopes:
            for path in sorted(scope_dir.rglob("*")):
                if not (path.is_file() and path.suffix.lower() in ALLOWED_MEMORY_EXTENSIONS):
                    continue
                file_name = path.relative_to(scope_dir).as_posix()
                seen.add((asset_id, file_name))
                content = path.read_text(encoding="utf-8", errors="replace")
                digest = content_hash(content)
                row = cur.execute(
                    "SELECT hash FROM files WHERE asset_id=? AND file_name=?",
                    (asset_id, file_name),
                ).fetchone()
                if row is not None and row[0] == digest:
                    continue
                self._reindex_file(cur, asset_id, file_name, content, digest)
                reindexed += 1
        # Remove deleted files from the index.
        for asset_id, file_name in cur.execute("SELECT asset_id, file_name FROM files").fetchall():
            if (asset_id, file_name) not in seen:
                self._delete_file(cur, asset_id, file_name)
        self._conn.commit()
        return reindexed

    def search(self, query: str, asset_id: str | None = None, limit: int = 8) -> list[SearchHit]:
        self.refresh()
        tokens = _tokenize(query)
        if not tokens:
            return []
        if self._fts_available:
            hits = self._search_fts(" ".join(f'"{t}"' for t in tokens), asset_id, limit)
            if not hits and len(tokens) > 1:
                hits = self._search_fts(" OR ".join(f'"{t}"' for t in tokens), asset_id, limit)
            return hits
        return self._search_like(tokens, asset_id, limit)

    # ------------------------------------------------------------------

    def _init_schema(self) -> bool:
        cur = self._conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS files (asset_id TEXT, file_name TEXT, hash TEXT, "
            "PRIMARY KEY (asset_id, file_name))"
        )
        try:
            cur.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(asset_id, file_name, content)"
            )
            self._conn.commit()
            return True
        except sqlite3.OperationalError:
            # FTS5 missing from this sqlite build: plain table + LIKE fallback.
            cur.execute(
                "CREATE TABLE IF NOT EXISTS chunks (asset_id TEXT, file_name TEXT, content TEXT)"
            )
            self._conn.commit()
            return False

    def _reindex_file(self, cur: sqlite3.Cursor, asset_id: str, file_name: str, content: str, digest: str) -> None:
        self._delete_file(cur, asset_id, file_name)
        for chunk in chunk_text(content):
            cur.execute(
                "INSERT INTO chunks (asset_id, file_name, content) VALUES (?, ?, ?)",
                (asset_id, file_name, chunk),
            )
        cur.execute(
            "INSERT OR REPLACE INTO files (asset_id, file_name, hash) VALUES (?, ?, ?)",
            (asset_id, file_name, digest),
        )

    def _delete_file(self, cur: sqlite3.Cursor, asset_id: str, file_name: str) -> None:
        cur.execute("DELETE FROM chunks WHERE asset_id=? AND file_name=?", (asset_id, file_name))
        cur.execute("DELETE FROM files WHERE asset_id=? AND file_name=?", (asset_id, file_name))

    def _search_fts(self, match: str, asset_id: str | None, limit: int) -> list[SearchHit]:
        sql = (
            "SELECT asset_id, file_name, "
            f"snippet(chunks, 2, '[', ']', ' … ', {SNIPPET_TOKENS}), bm25(chunks) "
            "FROM chunks WHERE chunks MATCH ?"
        )
        params: list[object] = [match]
        if asset_id:
            sql += " AND asset_id = ?"
            params.append(asset_id)
        sql += " ORDER BY bm25(chunks) LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [SearchHit(asset_id=r[0], file_name=r[1], snippet=r[2], score=r[3]) for r in rows]

    def _search_like(self, tokens: list[str], asset_id: str | None, limit: int) -> list[SearchHit]:
        sql = "SELECT asset_id, file_name, content FROM chunks WHERE " + " AND ".join(
            "content LIKE ?" for _ in tokens
        )
        params: list[object] = [f"%{t}%" for t in tokens]
        if asset_id:
            sql += " AND asset_id = ?"
            params.append(asset_id)
        sql += " LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [
            SearchHit(asset_id=r[0], file_name=r[1], snippet=r[2][:300], score=0.0) for r in rows
        ]


def _tokenize(query: str) -> list[str]:
    """Reduce a free-text query to safe FTS terms (alphanumeric tokens)."""
    return re.findall(r"[A-Za-z0-9_]+", query)[:12]


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def chunk_text(content: str) -> list[str]:
    """Paragraph-boundary chunking around CHUNK_TARGET_CHARS."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) > CHUNK_TARGET_CHARS:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks or ([content.strip()] if content.strip() else [])
