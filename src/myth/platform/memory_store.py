"""生产记忆的持久 SQLite 适配器。
以 kind/source_ref 去重并递增 revision，按 global/project/session 范围扫描全部可见候选；经历默认 context，不自动升级 verified。
"""

from __future__ import annotations

import re
import uuid
from typing import Iterable

from .memory import MemoryKind
from .retrieval import reciprocal_rank_scores


# SCHEMA：本仓储拥有的表、索引与约束；升级补齐旧字段，删除列须有迁移证据。
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


# 提取英文词项与中文二元片段供词面检索；相关度不是语义验证。
def _terms(text: str) -> set[str]:
    english = re.findall(r"[a-z0-9_]+", text.lower())
    chinese = re.findall(r"[一-鿿]+", text)
    return set(
        english
        + [part[i : i + 2] for part in chinese for i in range(max(1, len(part) - 1))]
    )


# 真实记忆聚合的 SQLite 所有者；作用域与事实等级显式保存，检索全可见候选。
class SqliteMemoryStore:
    # 复用 Runtime 连接建立持久有来源记忆表；检索是词面扫描，写入不会自动升级 verified。
    def __init__(self, runtime, *, vector_index=None) -> None:
        # runtime：共享 Runtime 装配对象；其 SQLite 连接只在所属线程使用。
        self.runtime = runtime
        # store：持久事实仓储；短事务维护本地一致性；外部效果不能并入数据库事务。
        self.store = runtime.store
        # vector_index：可选派生索引；Memory 行、scope、revision、active 才是权威事实。
        self.vector_index = vector_index
        self.store.db.executescript(SCHEMA)
        columns = {
            row["name"]
            for row in self.store.db.execute("PRAGMA table_info(workspace_memories)")
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

    # 校验 kind/text/source/scope/fact_level 后按来源更新或创建；同事务递增 revision，不凭经历升级 verified。
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
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
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
                    (
                        memory_id,
                        memory_kind.value,
                        value,
                        source,
                        scope,
                        scope_value,
                        level,
                    ),
                )
        record = self.get(memory_id)
        # 外部向量索引不是同一事务；失败只降级未来语义召回，权威记忆仍已提交。
        self._sync_vector_record(record)
        return record

    # 将当前 active revision 幂等投影到 Milvus；正文只用于 embedding，查询结果仍需回 SQLite hydration。
    def _sync_vector_record(self, record: dict) -> dict:
        if self.vector_index is None:
            return {"configured": False, "synced": 0}
        if not record.get("active"):
            return {"configured": True, "synced": 0}
        payload = [
            {
                "record_id": str(record["memory_id"]),
                "source_version": str(record["revision"]),
                "text": str(record["text"]),
                "scope_type": str(record.get("scope_type") or "global"),
                "scope_id": str(record.get("scope_id") or ""),
                "fact_level": str(record.get("fact_level") or "context"),
                "memory_kind": str(record.get("kind") or ""),
            }
        ]
        try:
            result = self.vector_index.sync_memories(payload)
            return {"configured": True, "synced": result.get("upserted", 0)}
        except RuntimeError:
            return {"configured": True, "synced": 0, "degraded": True}

    # 显式重建 active Memory 的派生向量索引；安装/迁移后可调用，失败不改变任何记忆事实。
    def rebuild_vector_index(self) -> dict:
        rows = self.store.db.execute(
            "SELECT * FROM workspace_memories WHERE active=1 ORDER BY rowid"
        ).fetchall()
        if self.vector_index is None:
            return {"configured": False, "memories": len(rows), "synced": 0}
        synced = 0
        degraded = False
        seen = 0
        # 重建是显式维护动作，扫描所有 active scope；实际召回仍在 hydration 时重新检查 scope。
        for row in rows:
            seen += 1
            result = self._sync_vector_record(dict(row))
            synced += int(result.get("synced") or 0)
            degraded = degraded or bool(result.get("degraded"))
        return {
            "configured": True,
            "memories": seen,
            "synced": synced,
            "degraded": degraded,
        }

    # 按身份取得已登记数据；缺失身份显式失败，调用方不能据此捏造已存在对象。
    def get(self, memory_id: str) -> dict:
        row = self.store.db.execute(
            "SELECT * FROM workspace_memories WHERE memory_id=?", (memory_id,)
        ).fetchone()
        if not row:
            raise KeyError(memory_id)
        return dict(row)

    # 返回当前目录/仓储的可见条目；排序和过滤只生成投影，不授予执行权。
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

    # 按 rowid 分页扫描当前作用域可见且 active 的记忆；避免 top-k 排序前删掉后部候选。
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
                (
                    item.value
                    if isinstance(item, MemoryKind)
                    else MemoryKind(str(item)).value
                )
                for item in kinds
            }
        rows = self.store.db.execute(
            "SELECT rowid AS candidate_cursor,* FROM workspace_memories "
            "WHERE active=1 AND rowid>? ORDER BY rowid LIMIT ?",
            (cursor, page_size + 1),
        ).fetchall()
        values = []
        for row in rows[:page_size]:
            item = dict(row)
            if allowed and item["kind"] not in allowed:
                continue
            scope = item.get("scope_type") or "global"
            scope_id = item.get("scope_id")
            visible = (
                scope == "global"
                or (
                    scope == "project"
                    and project_id is not None
                    and scope_id == project_id
                )
                or (
                    scope == "session"
                    and session_id is not None
                    and scope_id == session_id
                )
            )
            if visible:
                values.append(item)
        raw = list(rows[:page_size])
        next_cursor = int(raw[-1]["candidate_cursor"]) if raw else cursor
        return {
            "candidates": values,
            "cursor": cursor,
            "next_cursor": next_cursor,
            "has_more": len(rows) > page_size,
            "scanned": len(raw),
        }

    # 遍历所有可见候选后稳定排 top-k，返回扫描覆盖；Memory 内容只作上下文。
    def _lexical_search_report(
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
        query_terms = _terms(str(query))
        scored = []
        cursor = 0
        scanned = 0
        visible = 0
        matched = 0
        pages = 0
        while True:
            page = self.candidates(
                cursor=cursor,
                page_size=200,
                project_id=project_id,
                session_id=session_id,
                kinds=kinds,
            )
            pages += 1
            scanned += page["scanned"]
            for item in page["candidates"]:
                visible += 1
                score = len(query_terms & _terms(item["text"]))
                if not query_terms or score:
                    matched += 1
                    scored.append((score, int(item["candidate_cursor"]), item))
            # 仍扫描全部候选，但每页只保留稳定 top-k；大记忆库不能积累所有命中正文再全排序。
            if len(scored) > limit:
                scored.sort(key=lambda item: (-item[0], -item[1], item[2]["memory_id"]))
                del scored[limit:]
            cursor = page["next_cursor"]
            if not page["has_more"]:
                break
        scored.sort(key=lambda item: (-item[0], -item[1], item[2]["memory_id"]))
        results = []
        for _, _, item in scored[:limit]:
            value = dict(item)
            value.pop("candidate_cursor", None)
            results.append(value)
        return {
            "memories": results,
            "retrieval": {
                "backend": "memory-lexical",
                "candidate_policy": "all-visible-active-memories-v2",
                "scanned": scanned,
                "visible": visible,
                "matched": matched,
                "pages": pages,
                "exhausted": True,
                "truncated_before_ranking": False,
            },
        }

    # 校验 Memory 当前是否对作用域可见；向量 metadata 不能代替这一权威检查。
    @staticmethod
    def _visible(item: dict, project_id: str | None, session_id: str | None) -> bool:
        scope = item.get("scope_type") or "global"
        scope_id = item.get("scope_id")
        return (
            scope == "global"
            or (scope == "project" and project_id is not None and scope_id == project_id)
            or (scope == "session" and session_id is not None and scope_id == session_id)
        )

    # 词面召回始终保底；Milvus 只贡献候选排名，命中经 active/revision/scope/kind hydration 后用 RRF 融合。
    def search_report(
        self,
        query: str,
        *,
        kinds: Iterable[str | MemoryKind] | None = None,
        limit: int = 6,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        lexical = self._lexical_search_report(
            query,
            kinds=kinds,
            limit=limit,
            project_id=project_id,
            session_id=session_id,
        )
        if self.vector_index is None or not str(query).strip():
            return lexical

        allowed = None
        if kinds is not None:
            allowed = {
                item.value if isinstance(item, MemoryKind) else MemoryKind(str(item)).value
                for item in kinds
            }
        try:
            hits = self.vector_index.search_memories(
                str(query), limit=max(32, int(limit) * 8)
            )
        except RuntimeError:
            lexical["retrieval"]["vector_status"] = "unavailable"
            lexical["retrieval"]["degraded"] = True
            return lexical

        vector_rows = []
        stale_rejected = 0
        for hit in hits:
            memory_id = str(hit.get("record_id") or "")
            row = self.store.db.execute(
                "SELECT * FROM workspace_memories WHERE memory_id=?", (memory_id,)
            ).fetchone()
            if row is None:
                stale_rejected += 1
                continue
            item = dict(row)
            if (
                not item.get("active")
                or str(item.get("revision")) != str(hit.get("source_version") or "")
                or not self._visible(item, project_id, session_id)
                or (allowed and item.get("kind") not in allowed)
            ):
                stale_rejected += 1
                continue
            item["vector_distance"] = hit.get("distance")
            vector_rows.append(item)

        lexical_rows = list(lexical["memories"])
        identity = lambda item: str(item["memory_id"])
        rrf = reciprocal_rank_scores(
            (
                tuple(identity(item) for item in lexical_rows),
                tuple(identity(item) for item in vector_rows),
            )
        )
        merged = {}
        for item in lexical_rows + vector_rows:
            key = identity(item)
            if key not in merged:
                merged[key] = dict(item)
        memories = []
        for key, item in merged.items():
            item["hybrid_score"] = round(rrf.get(key, 0.0), 8)
            memories.append(item)
        memories.sort(
            key=lambda item: (
                -float(item.get("hybrid_score") or 0.0),
                -int(item.get("revision") or 0),
                item["memory_id"],
            )
        )
        return {
            "memories": memories[:limit],
            "retrieval": {
                **lexical["retrieval"],
                "backend": "memory-lexical+milvus",
                "candidate_policy": "visible-active-lexical+milvus-hydrated-rrf-v1",
                "vector_candidates": len(hits),
                "vector_hydrated": len(vector_rows),
                "vector_stale_rejected": stale_rejected,
                "vector_status": "ready",
                "degraded": False,
            },
        }

    # 把同一 Memory 投影为 L0/L1/L2；source_ref 固定 memory_id@revision，表示粒度不会悄悄换源。
    def resolve(
        self,
        memory_id: str,
        *,
        resolution: str = "L2",
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        item = self.get(str(memory_id))
        if not item.get("active") or not self._visible(item, project_id, session_id):
            raise PermissionError("memory is not visible in the admitted scope")
        level = str(resolution or "L2").upper()
        if level not in {"L0", "L1", "L2"}:
            raise ValueError("resolution must be L0/L1/L2")
        text = str(item.get("text") or "")
        stable_ref = f"memory:{item['memory_id']}@{item['revision']}"
        base = {
            "memory_id": item["memory_id"],
            "kind": item["kind"],
            "source_ref": stable_ref,
            "provenance_ref": item["source_ref"],
            "scope_type": item.get("scope_type") or "global",
            "scope_id": item.get("scope_id"),
            "fact_level": item.get("fact_level") or "context",
            "revision": item["revision"],
            "resolution": level,
        }
        if level == "L0":
            return {**base, "text": text[:360], "bytes": len(text.encode("utf-8"))}
        if level == "L1":
            segments = [text[start : start + 800] for start in range(0, len(text), 800)]
            return {
                **base,
                "text": text[:1200],
                "segments": [
                    {"index": index, "preview": segment[:240]}
                    for index, segment in enumerate(segments[:12])
                ],
                "segment_count": len(segments),
                "bytes": len(text.encode("utf-8")),
            }
        return {**base, "text": text, "bytes": len(text.encode("utf-8"))}

    # 搜索先只返回 L0 索引视图和同一次召回报告；避免为了观测元数据重复执行向量查询。
    def search_view_report(
        self,
        query: str,
        *,
        kinds: Iterable[str | MemoryKind] | None = None,
        limit: int = 6,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        report = self.search_report(
            query,
            kinds=kinds,
            limit=limit,
            project_id=project_id,
            session_id=session_id,
        )
        views = [
            self.resolve(
                item["memory_id"],
                resolution="L0",
                project_id=project_id,
                session_id=session_id,
            )
            for item in report["memories"]
        ]
        return {"memories": views, "retrieval": report["retrieval"]}

    # 兼容调用只取 L0 结果；完整观测使用 search_view_report，避免把正文直接塞进初始 Context。
    def search_views(
        self,
        query: str,
        *,
        kinds: Iterable[str | MemoryKind] | None = None,
        limit: int = 6,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> list[dict]:
        return self.search_view_report(
            query,
            kinds=kinds,
            limit=limit,
            project_id=project_id,
            session_id=session_id,
        )["memories"]

    # 以命中 Memory 为锚点读取邻近同作用域记录，提供 chronology/navigation；不是新事实，也不改变 revision。
    def timeline(
        self,
        memory_id: str,
        *,
        radius: int = 2,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        if type(radius) is not int or not 0 <= radius <= 5:
            raise ValueError("radius must be 0-5")
        anchor = self.get(str(memory_id))
        if not anchor.get("active") or not self._visible(anchor, project_id, session_id):
            raise PermissionError("memory is not visible in the admitted scope")
        row = self.store.db.execute(
            "SELECT rowid FROM workspace_memories WHERE memory_id=?", (memory_id,)
        ).fetchone()
        center = int(row["rowid"])
        rows = self.store.db.execute(
            "SELECT rowid,* FROM workspace_memories WHERE active=1 AND rowid BETWEEN ? AND ? ORDER BY rowid",
            (max(1, center - radius * 3), center + radius * 3),
        ).fetchall()
        visible = [
            dict(item)
            for item in rows
            if self._visible(dict(item), project_id, session_id)
        ]
        before = [item for item in visible if int(item["rowid"]) < center][-radius:]
        after = [item for item in visible if int(item["rowid"]) > center][:radius]
        ordered = before + [dict(anchor)] + after
        return {
            "anchor": f"memory:{anchor['memory_id']}@{anchor['revision']}",
            "memories": [
                self.resolve(
                    item["memory_id"],
                    resolution="L0",
                    project_id=project_id,
                    session_id=session_id,
                )
                for item in ordered
            ],
            "radius": radius,
        }

    # 读取当前作用域的检索结果；相似度只用于排序，不升级为已验证事实。
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

    # 撤销条目在未来查询中的可见性；历史快照与已发生效果不被倒写。
    def revoke(self, memory_id: str) -> dict:
        current = self.get(memory_id)
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "UPDATE workspace_memories SET active=0,revision=revision+1,"
                "updated_at=CURRENT_TIMESTAMP WHERE memory_id=?",
                (memory_id,),
            )
        return self.get(memory_id)

    # 以 Run 来源幂等记录结束经历，按冻结项目/会话范围保存；不宣称回答为 verified。
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
        scope_id = (
            row["project_id"]
            if row and row["project_id"]
            else (row["session_id"] if row else run_id)
        )
        return self.remember(
            kind=MemoryKind.EPISODIC,
            text=text,
            source_ref=f"run:{run_id}",
            scope_type=scope_type,
            scope_id=scope_id,
            fact_level="context",
        )
