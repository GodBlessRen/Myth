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
    scope_type TEXT NOT NULL DEFAULT 'global',
    scope_id TEXT,
    fact_level TEXT NOT NULL DEFAULT 'context',
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
        columns = {
            row["name"] for row in self.store.db.execute("PRAGMA table_info(workspace_memories)")
        }
        if "scope_type" not in columns:
            self.store.db.execute(
                "ALTER TABLE workspace_memories ADD COLUMN scope_type TEXT NOT NULL DEFAULT 'global'"
            )
        if "scope_id" not in columns:
            self.store.db.execute(
                "ALTER TABLE workspace_memories ADD COLUMN scope_id TEXT"
            )
        if "fact_level" not in columns:
            self.store.db.execute(
                "ALTER TABLE workspace_memories ADD COLUMN fact_level TEXT NOT NULL DEFAULT 'context'"
            )

    def remember(
        self,
        *,
        kind: str | MemoryKind,
        text: str,
        source_ref: str,
        scope_type: str = "global",
        scope_id: str | None = None,
        fact_level: str = "context",
    ) -> dict:
        memory_kind = kind if isinstance(kind, MemoryKind) else MemoryKind(str(kind))
        value = str(text).strip()
        source = str(source_ref).strip()
        if not value or len(value.encode("utf-8")) > 16_000:
            raise ValueError("memory text must contain 1-16000 UTF-8 bytes")
        if not source or len(source) > 500:
            raise ValueError("memory source_ref is required")
        scope = str(scope_type or "global").strip().lower()
        if scope not in {"global", "project", "session"}:
            raise ValueError("memory scope_type must be global/project/session")
        scope_value = None if scope == "global" else str(scope_id or "").strip()
        if scope != "global" and (not scope_value or len(scope_value) > 200):
            raise ValueError("scoped memory requires scope_id")
        level = str(fact_level or "context").strip().lower()
        if level not in {"context", "user_asserted", "verified"}:
            raise ValueError("memory fact_level must be context/user_asserted/verified")
        with self.store.tx() as db:
            row = db.execute(
                "SELECT * FROM workspace_memories WHERE kind=? AND source_ref=?",
                (memory_kind.value, source),
            ).fetchone()
            if row:
                revision = int(row["revision"]) + 1
                db.execute(
                    "UPDATE workspace_memories SET text=?,scope_type=?,scope_id=?,fact_level=?,"
                    "revision=?,active=1,updated_at=CURRENT_TIMESTAMP WHERE memory_id=?",
                    (value, scope, scope_value, level, revision, row["memory_id"]),
                )
                memory_id = str(row["memory_id"])
            else:
                memory_id = f"mem_{uuid.uuid4().hex}"
                db.execute(
                    "INSERT INTO workspace_memories(memory_id,kind,text,source_ref,scope_type,scope_id,fact_level) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (memory_id, memory_kind.value, value, source, scope, scope_value, level),
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

    def candidates(
        self,
        *,
        cursor: int = 0,
        page_size: int = 200,
        project_id: str | None = None,
        session_id: str | None = None,
        kinds: Iterable[str | MemoryKind] | None = None,
    ) -> dict:
        if type(cursor) is not int or cursor < 0:
            raise ValueError("cursor must be a non-negative integer")
        if type(page_size) is not int or not 1 <= page_size <= 500:
            raise ValueError("page_size must be 1-500")
        allowed = None
        if kinds is not None:
            allowed = {
                item.value if isinstance(item, MemoryKind) else MemoryKind(str(item)).value
                for item in kinds
            }
        rows = self.store.db.execute(
            "SELECT rowid AS candidate_cursor,* FROM workspace_memories "
            "WHERE active=1 AND rowid>? ORDER BY rowid LIMIT ?",
            (cursor, page_size + 1),
        ).fetchall()
        values=[]
        for row in rows[:page_size]:
            item=dict(row)
            if allowed and item["kind"] not in allowed:
                continue
            scope=item.get("scope_type") or "global"
            scope_id=item.get("scope_id")
            visible=(
                scope=="global"
                or (scope=="project" and project_id is not None and scope_id==project_id)
                or (scope=="session" and session_id is not None and scope_id==session_id)
            )
            if visible:
                values.append(item)
        raw=list(rows[:page_size])
        next_cursor=int(raw[-1]["candidate_cursor"]) if raw else cursor
        return {
            "candidates":values,
            "cursor":cursor,
            "next_cursor":next_cursor,
            "has_more":len(rows)>page_size,
            "scanned":len(raw),
        }

    def search_report(
        self,
        query: str,
        *,
        kinds: Iterable[str | MemoryKind] | None = None,
        limit: int = 6,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("limit must be 1-20")
        query_terms=_terms(str(query))
        scored=[];cursor=0;scanned=0;visible=0;matched=0;pages=0
        while True:
            page=self.candidates(
                cursor=cursor,
                page_size=200,
                project_id=project_id,
                session_id=session_id,
                kinds=kinds,
            )
            pages+=1;scanned+=page["scanned"]
            for item in page["candidates"]:
                visible+=1
                score=len(query_terms & _terms(item["text"]))
                if not query_terms or score:
                    matched+=1
                    scored.append((score,int(item["candidate_cursor"]),item))
            cursor=page["next_cursor"]
            if not page["has_more"]:break
        scored.sort(key=lambda item:(-item[0],-item[1],item[2]["memory_id"]))
        results=[]
        for _,_,item in scored[:limit]:
            value=dict(item);value.pop("candidate_cursor",None);results.append(value)
        return {
            "memories":results,
            "retrieval":{
                "backend":"memory-lexical",
                "candidate_policy":"all-visible-active-memories-v2",
                "scanned":scanned,
                "visible":visible,
                "matched":matched,
                "pages":pages,
                "exhausted":True,
                "truncated_before_ranking":False,
            },
        }

    def search(
        self,
        query: str,
        *,
        kinds: Iterable[str | MemoryKind] | None = None,
        limit: int = 6,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> list[dict]:
        return self.search_report(
            query,
            kinds=kinds,
            limit=limit,
            project_id=project_id,
            session_id=session_id,
        )["memories"]

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
        row = self.store.db.execute(
            "SELECT t.session_id,s.project_id FROM workspace_turns t "
            "JOIN workspace_sessions s ON s.id=t.session_id WHERE t.run_id=?",
            (run_id,),
        ).fetchone()
        scope_type = "project" if row and row["project_id"] else "session"
        scope_id = row["project_id"] if row and row["project_id"] else (row["session_id"] if row else run_id)
        return self.remember(
            kind=MemoryKind.EPISODIC,
            text=text,
            source_ref=f"run:{run_id}",
            scope_type=scope_type,
            scope_id=scope_id,
            fact_level="context",
        )

