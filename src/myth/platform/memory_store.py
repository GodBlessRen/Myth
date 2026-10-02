"""Persistent typed memory with explicit provenance and revision semantics."""

from __future__ import annotations

import re
import uuid
from typing import Iterable

from .memory import MemoryKind


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS workspace_memories(
    memory_id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kind, source_ref)
);
"""


def _terms(text: str) -> set[str]:
    english = re.findall(r"[a-z0-9_]+", text.lower())
    chinese = re.findall(r"[一-鿿]+", text)
    return set(english + [part[i:i+2] for part in chinese for i in range(max(1, len(part)-1))])


class SqliteMemoryStore:
    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.store = runtime.store
        self.store.db.executescript(SCHEMA)

    def remember(
        self,
        *,
        kind: str | MemoryKind,
        text: str,
        source_ref: str,
    ) -> dict:
        memory_kind = kind if isinstance(kind, MemoryKind) else MemoryKind(str(kind))
        value = str(text).strip()
        source = str(source_ref).strip()
        if not value or len(value.encode("utf-8")) > 16_000:
            raise ValueError("memory text must contain 1-16000 UTF-8 bytes")
        if not source or len(source) > 500:
            raise ValueError("memory source_ref is required")
        with self.store.tx() as db:
            row = db.execute(
                "SELECT * FROM workspace_memories WHERE kind=? AND source_ref=?",
                (memory_kind.value, source),
            ).fetchone()
            if row:
                revision = int(row["revision"]) + 1
                db.execute(
                    "UPDATE workspace_memories SET text=?,revision=?,active=1,"
                    "updated_at=CURRENT_TIMESTAMP WHERE memory_id=?",
                    (value, revision, row["memory_id"]),
                )
                memory_id = str(row["memory_id"])
            else:
                memory_id = f"mem_{uuid.uuid4().hex}"
                db.execute(
                    "INSERT INTO workspace_memories(memory_id,kind,text,source_ref) VALUES (?,?,?,?)",
                    (memory_id, memory_kind.value, value, source),
                )
        return self.get(memory_id)

    def get(self, memory_id: str) -> dict:
        row = self.store.db.execute(
            "SELECT * FROM workspace_memories WHERE memory_id=?", (memory_id,)
        ).fetchone()
        if not row:
            raise KeyError(memory_id)
        return dict(row)

    def list(self, *, active_only: bool = True, limit: int = 100) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("limit must be 1-500")
        sql = "SELECT * FROM workspace_memories"
        args: tuple = ()
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY updated_at DESC,rowid DESC LIMIT ?"
        args = (limit,)
        return [dict(row) for row in self.store.db.execute(sql, args).fetchall()]

    def search(
        self,
        query: str,
        *,
        kinds: Iterable[str | MemoryKind] | None = None,
        limit: int = 6,
    ) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("limit must be 1-20")
        allowed = None
        if kinds is not None:
            allowed = {
                item.value if isinstance(item, MemoryKind) else MemoryKind(str(item)).value
                for item in kinds
            }
        query_terms = _terms(str(query))
        scored: list[tuple[int, int, dict]] = []
        for index, row in enumerate(self.list(active_only=True, limit=500)):
            if allowed and row["kind"] not in allowed:
                continue
            score = len(query_terms & _terms(row["text"]))
            if not query_terms or score:
                scored.append((score, -index, row))
        scored.sort(key=lambda item: (-item[0], -item[1], item[2]["memory_id"]))
        return [row for _, _, row in scored[:limit]]

    def revoke(self, memory_id: str) -> dict:
        current = self.get(memory_id)
        with self.store.tx() as db:
            db.execute(
                "UPDATE workspace_memories SET active=0,revision=revision+1,"
                "updated_at=CURRENT_TIMESTAMP WHERE memory_id=?",
                (memory_id,),
            )
        return self.get(memory_id)

    def record_episode(self, run_id: str, user_text: str, assistant_text: str) -> dict:
        text = f"User: {user_text.strip()}\nAssistant: {assistant_text.strip()}"
        if len(text.encode("utf-8")) > 8_000:
            text = text.encode("utf-8")[:8_000].decode("utf-8", errors="ignore")
        return self.remember(
            kind=MemoryKind.EPISODIC,
            text=text,
            source_ref=f"run:{run_id}",
        )
