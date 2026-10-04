"""Mental Model 与 Knowledge Page 的持久派生视图。
Mental Model 是基于 Memory 的 materialized view；Knowledge Page 只拥有树结构，正文唯一存放在 backing Memory。
刷新分为 prepare -> synthesis(outside store) -> commit：模型只提出正文，SQLite 负责 freshness、证据和原子发布。
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Iterable


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS workspace_mental_models(
    model_id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    source_query TEXT NOT NULL,
    scope_type TEXT NOT NULL DEFAULT 'global',
    scope_id TEXT,
    backing_memory_id TEXT REFERENCES workspace_memories(memory_id),
    revision INTEGER NOT NULL DEFAULT 1,
    last_seen_change_seq INTEGER NOT NULL DEFAULT 0,
    last_refreshed_at TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scope_type, scope_id, name)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_mental_models_scope_name
    ON workspace_mental_models(scope_type, COALESCE(scope_id,''), name);

CREATE TABLE IF NOT EXISTS workspace_mental_model_revisions(
    model_id TEXT NOT NULL REFERENCES workspace_mental_models(model_id),
    revision INTEGER NOT NULL,
    backing_memory_id TEXT,
    backing_memory_revision INTEGER,
    source_change_seq INTEGER NOT NULL,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(model_id, revision)
);

CREATE TABLE IF NOT EXISTS workspace_knowledge_pages(
    node_id TEXT PRIMARY KEY NOT NULL,
    parent_id TEXT REFERENCES workspace_knowledge_pages(node_id) ON DELETE CASCADE,
    node_type TEXT NOT NULL CHECK(node_type IN ('folder','page')),
    name TEXT NOT NULL,
    mental_model_id TEXT REFERENCES workspace_mental_models(model_id),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(
        (node_type='folder' AND mental_model_id IS NULL)
        OR (node_type='page' AND mental_model_id IS NOT NULL)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_knowledge_pages_sibling_name
    ON workspace_knowledge_pages(COALESCE(parent_id,''), name);
"""


# _clean_name：名称进入 durable identity/UI 前统一约束；不允许空白或超长字符串形成隐式层级。
def _clean_name(value: str, *, field: str = "name", max_length: int = 160) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_length:
        raise ValueError(f"{field} must contain 1-{max_length} characters")
    return text


# _clean_scope：复用 Memory 的 global/project/session 语义；Mental Model 不创建第四套作用域。
def _clean_scope(scope_type: str, scope_id: str | None) -> tuple[str, str | None]:
    scope = str(scope_type or "global").strip().lower()
    if scope not in {"global", "project", "session"}:
        raise ValueError("scope_type must be global/project/session")
    value = None if scope == "global" else str(scope_id or "").strip()
    if scope != "global" and (not value or len(value) > 200):
        raise ValueError("scoped mental model requires scope_id")
    return scope, value


# SqliteKnowledgeViews：一个深模块同时拥有 materialized Memory view 与其导航树，避免内容/树双写真相。
class SqliteKnowledgeViews:
    # 复用同一 Runtime/MemoryStore；所有派生正文仍通过 MemoryStore 写入，Milvus/证据/freshness 合同不复制。
    def __init__(self, runtime, memory_store) -> None:
        # runtime：共享 Runtime 装配对象；这里只复用其 SQLite 生命周期，不取得执行授权。
        self.runtime = runtime
        # store：持久 SQLite 状态所有者；Mental Model/Page 的事务都通过同一连接提交。
        self.store = runtime.store
        # memory：现有权威 Memory Store；派生视图复用其 Evidence/revision/freshness，不复制正文生命周期。
        self.memory = memory_store
        self.store.ensure_schema(SCHEMA)

    # create_model：只登记“持续回答什么问题”；不偷偷调用模型，也不把空壳宣称已刷新。
    def create_model(
        self,
        *,
        name: str,
        source_query: str,
        scope_type: str = "global",
        scope_id: str | None = None,
        model_id: str | None = None,
        _db=None,
    ) -> dict[str, Any]:
        title = _clean_name(name)
        query = _clean_name(source_query, field="source_query", max_length=1000)
        scope, scope_value = _clean_scope(scope_type, scope_id)
        identity = str(model_id or f"mm_{uuid.uuid4().hex}").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", identity):
            raise ValueError("model_id contains unsupported characters")
        with self.store.transaction_scope(_db) as db:
            db.execute(
                "INSERT INTO workspace_mental_models("
                "model_id,name,source_query,scope_type,scope_id"
                ") VALUES (?,?,?,?,?)",
                (identity, title, query, scope, scope_value),
            )
        return self.model(identity)

    # model：返回 Mental Model 元数据和可验证 staleness；正文按需从 backing Memory 解析。
    def model(self, model_id: str, *, resolution: str = "L0") -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM workspace_mental_models WHERE model_id=?", (str(model_id),)
        ).fetchone()
        if row is None:
            raise KeyError(model_id)
        value = dict(row)
        changes = self._scope_changes(value, int(value["last_seen_change_seq"]), limit=1)
        value["is_stale"] = bool(changes)
        value["freshness"] = (
            "unmaterialized"
            if not value.get("backing_memory_id")
            else ("stale" if changes else "fresh")
        )
        if value.get("backing_memory_id"):
            value["content"] = self.memory.resolve(
                str(value["backing_memory_id"]),
                resolution=resolution,
                project_id=(
                    str(value["scope_id"]) if value["scope_type"] == "project" else None
                ),
                session_id=(
                    str(value["scope_id"]) if value["scope_type"] == "session" else None
                ),
            )
        else:
            value["content"] = None
        return value

    # list_models：列表只返回紧凑状态，避免为了页面目录批量展开正文/Evidence。
    def list_models(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT model_id FROM workspace_mental_models"
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY updated_at DESC,model_id"
        return [
            self.model(str(row["model_id"]), resolution="L0")
            for row in self.store.db.execute(sql).fetchall()
        ]

    # _scope_changes：Mental Model staleness 只由自身 scope 的 Memory change 决定，不使用 bank/global 近似冒充准确值。
    def _scope_changes(
        self, model: dict[str, Any], after_seq: int, *, limit: int = 1000
    ) -> list[dict[str, Any]]:
        project_id = (
            str(model["scope_id"]) if model["scope_type"] == "project" else None
        )
        session_id = (
            str(model["scope_id"]) if model["scope_type"] == "session" else None
        )
        changes = self.memory.changes_since(
            int(after_seq),
            project_id=project_id,
            session_id=session_id,
            limit=limit,
        )
        backing_id = str(model.get("backing_memory_id") or "")
        return [item for item in changes if str(item["memory_id"]) != backing_id]

    # prepare_refresh：固定本次 synthesis 的来源版本与水位；LLM 调用必须发生在该方法之外。
    def prepare_refresh(
        self,
        model_id: str,
        *,
        limit: int = 12,
        resolution: str = "L1",
    ) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("limit must be 1-50")
        model = self.model(model_id, resolution="L0")
        if not model.get("active"):
            raise ValueError("mental model is inactive")
        project_id = (
            str(model["scope_id"]) if model["scope_type"] == "project" else None
        )
        session_id = (
            str(model["scope_id"]) if model["scope_type"] == "session" else None
        )
        report = self.memory.search_report(
            str(model["source_query"]),
            limit=min(20, limit),
            project_id=project_id,
            session_id=session_id,
        )
        source_rows = [
            row
            for row in report["memories"]
            if not str(row.get("source_ref") or "").startswith("mental-model:")
            and str(row.get("memory_id") or "") != str(model.get("backing_memory_id") or "")
        ][:limit]
        sources = [
            self.memory.resolve(
                str(row["memory_id"]),
                resolution=resolution,
                project_id=project_id,
                session_id=session_id,
            )
            for row in source_rows
        ]
        previous_content = ""
        if model.get("backing_memory_id"):
            previous_content = str(
                self.memory.resolve(
                    str(model["backing_memory_id"]),
                    resolution="L2",
                    project_id=project_id,
                    session_id=session_id,
                ).get("text")
                or ""
            )
        return {
            "model_id": str(model["model_id"]),
            "model_revision": int(model["revision"]),
            "name": str(model["name"]),
            "source_query": str(model["source_query"]),
            "scope_type": str(model["scope_type"]),
            "scope_id": model.get("scope_id"),
            # previous_content：仅作为“待演进文档基线”；不能自动进入 evidence_refs 或获得事实权重。
            "previous_content": previous_content,
            "observed_change_seq": self.memory.current_change_seq(),
            "sources": sources,
            "retrieval": report["retrieval"],
        }

    # commit_refresh：在同一 SQLite 事务核对 model revision + scope watermark，再提交 backing Memory 与模型版本。
    def commit_refresh(
        self,
        model_id: str,
        *,
        content: str,
        evidence_memory_ids: Iterable[str],
        expected_model_revision: int,
        observed_change_seq: int,
    ) -> dict[str, Any]:
        body = str(content or "").strip()
        if not body or len(body.encode("utf-8")) > 16_000:
            raise ValueError("mental model content must contain 1-16000 UTF-8 bytes")
        evidence_ids = tuple(dict.fromkeys(str(item).strip() for item in evidence_memory_ids))
        if not evidence_ids or any(not item for item in evidence_ids):
            raise ValueError("mental model refresh requires evidence Memory ids")

        with self.store.tx() as db:
            row = db.execute(
                "SELECT * FROM workspace_mental_models WHERE model_id=?", (str(model_id),)
            ).fetchone()
            if row is None:
                raise KeyError(model_id)
            model = dict(row)
            if not bool(model["active"]):
                raise ValueError("mental model is inactive")
            if int(model["revision"]) != int(expected_model_revision):
                raise ValueError("mental model revision changed during refresh")
            if self._scope_changes(model, int(observed_change_seq), limit=1):
                raise ValueError("mental model source scope changed during refresh")

            project_id = (
                str(model["scope_id"]) if model["scope_type"] == "project" else None
            )
            session_id = (
                str(model["scope_id"]) if model["scope_type"] == "session" else None
            )
            evidence = []
            for memory_id in evidence_ids:
                try:
                    self.memory.resolve(
                        memory_id,
                        resolution="L0",
                        project_id=project_id,
                        session_id=session_id,
                    )
                except (KeyError, PermissionError) as exc:
                    raise ValueError(
                        f"mental model evidence is not visible: {memory_id}"
                    ) from exc
                source = self.memory.get(memory_id)
                if str(source.get("source_ref") or "").startswith("mental-model:"):
                    raise ValueError("mental model refresh cannot cite synthesized models")
                evidence.append(
                    {
                        "source_memory_id": memory_id,
                        "relevance": f"materialized view source: {model['source_query']}",
                    }
                )

            backing = self.memory.remember(
                kind="semantic",
                text=body,
                source_ref=f"mental-model:{model_id}",
                scope_type=str(model["scope_type"]),
                scope_id=model.get("scope_id"),
                fact_level="context",
                evidence=evidence,
                _db=db,
            )
            new_revision = int(model["revision"]) + 1
            # backing Memory 写入已追加 change_seq；刷新水位推进到事务内最新值，避免把自身发布判成 stale。
            watermark = self.memory.current_change_seq()
            db.execute(
                "UPDATE workspace_mental_models SET backing_memory_id=?,revision=?,"
                "last_seen_change_seq=?,last_refreshed_at=CURRENT_TIMESTAMP,"
                "updated_at=CURRENT_TIMESTAMP WHERE model_id=?",
                (
                    str(backing["memory_id"]),
                    new_revision,
                    watermark,
                    str(model_id),
                ),
            )
            db.execute(
                "INSERT INTO workspace_mental_model_revisions("
                "model_id,revision,backing_memory_id,backing_memory_revision,"
                "source_change_seq,evidence_count"
                ") VALUES (?,?,?,?,?,?)",
                (
                    str(model_id),
                    new_revision,
                    str(backing["memory_id"]),
                    int(backing["revision"]),
                    watermark,
                    len(evidence),
                ),
            )

        # Milvus 是事务外派生索引；业务提交成功后再同步 backing Memory。
        self.memory._sync_vector_record(backing)
        return self.model(str(model_id), resolution="L1")

    # create_folder：Knowledge Page 层只创建树容器，不拥有正文。
    def create_folder(
        self,
        name: str,
        *,
        parent_id: str | None = None,
        sort_order: int = 0,
    ) -> dict[str, Any]:
        return self._create_node(
            node_type="folder",
            name=name,
            parent_id=parent_id,
            mental_model_id=None,
            sort_order=sort_order,
        )

    # create_page：页面引用一个现有 Mental Model；树节点删除/移动不复制或改写其正文。
    def create_page(
        self,
        name: str,
        *,
        mental_model_id: str,
        parent_id: str | None = None,
        sort_order: int = 0,
    ) -> dict[str, Any]:
        self.model(mental_model_id, resolution="L0")
        return self._create_node(
            node_type="page",
            name=name,
            parent_id=parent_id,
            mental_model_id=mental_model_id,
            sort_order=sort_order,
        )

    # create_page_with_model：同事务登记问题与树节点；任一约束失败都不留下孤儿 Mental Model。
    def create_page_with_model(
        self,
        *,
        name: str,
        source_query: str,
        parent_id: str | None = None,
        scope_type: str = "global",
        scope_id: str | None = None,
        sort_order: int = 0,
    ) -> dict[str, Any]:
        with self.store.tx() as db:
            model = self.create_model(
                name=name,
                source_query=source_query,
                scope_type=scope_type,
                scope_id=scope_id,
                _db=db,
            )
            page = self._create_node(
                node_type="page",
                name=name,
                parent_id=parent_id,
                mental_model_id=str(model["model_id"]),
                sort_order=sort_order,
                _db=db,
            )
        return {
            "page": self.node(str(page["node_id"])),
            "mental_model": self.model(str(model["model_id"]), resolution="L0"),
        }

    # _create_node：父节点必须是 folder；同级名称唯一，正文身份由 mental_model_id 显式引用。
    def _create_node(
        self,
        *,
        node_type: str,
        name: str,
        parent_id: str | None,
        mental_model_id: str | None,
        sort_order: int,
        _db=None,
    ) -> dict[str, Any]:
        title = _clean_name(name)
        if type(sort_order) is not int:
            raise ValueError("sort_order must be an integer")
        identity = f"kp_{uuid.uuid4().hex}"
        with self.store.transaction_scope(_db) as db:
            if parent_id is not None:
                parent = db.execute(
                    "SELECT node_type FROM workspace_knowledge_pages WHERE node_id=?",
                    (str(parent_id),),
                ).fetchone()
                if parent is None or parent["node_type"] != "folder":
                    raise ValueError("knowledge page parent must be a folder")
            db.execute(
                "INSERT INTO workspace_knowledge_pages("
                "node_id,parent_id,node_type,name,mental_model_id,sort_order"
                ") VALUES (?,?,?,?,?,?)",
                (
                    identity,
                    parent_id,
                    node_type,
                    title,
                    mental_model_id,
                    sort_order,
                ),
            )
        if _db is not None:
            return {
                "node_id": identity,
                "parent_id": parent_id,
                "node_type": node_type,
                "name": title,
                "mental_model_id": mental_model_id,
                "sort_order": sort_order,
            }
        return self.node(identity)

    # node：page 默认返回 Mental Model L0，folder 只返回结构；调用方按需再展开。
    def node(self, node_id: str, *, resolution: str = "L0") -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM workspace_knowledge_pages WHERE node_id=?", (str(node_id),)
        ).fetchone()
        if row is None:
            raise KeyError(node_id)
        value = dict(row)
        value["mental_model"] = (
            self.model(str(value["mental_model_id"]), resolution=resolution)
            if value.get("mental_model_id")
            else None
        )
        return value

    # tree：一次读取结构并递归装配；page 只附带模型摘要，避免目录视图展开全文。
    def tree(self) -> list[dict[str, Any]]:
        rows = [
            dict(row)
            for row in self.store.db.execute(
                "SELECT * FROM workspace_knowledge_pages "
                "ORDER BY parent_id IS NOT NULL,parent_id,sort_order,name,node_id"
            ).fetchall()
        ]
        by_parent: dict[str | None, list[dict[str, Any]]] = {}
        for row in rows:
            row["children"] = []
            if row["node_type"] == "page":
                row["mental_model"] = self.model(
                    str(row["mental_model_id"]), resolution="L0"
                )
            else:
                row["mental_model"] = None
            by_parent.setdefault(row.get("parent_id"), []).append(row)
        for row in rows:
            row["children"] = by_parent.get(str(row["node_id"]), [])
        return by_parent.get(None, [])
