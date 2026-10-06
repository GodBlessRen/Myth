"""知识文档、分片和召回的 SQLite 适配器。
只拥有 documents/chunks；项目身份由只读协作者核对。原始对象先发布，文档与分片
同事务提交，Milvus 仅在提交后更新派生索引。Conversation 通过本仓储冻结来源，
本仓储不创建 Turn、模型调用、预算或执行 Ticket。
"""

from __future__ import annotations

import uuid

from ..conversation import chunks, score_chunk
from ..domain import digest_json
from ..platform.retrieval import reciprocal_rank_scores

# SCHEMA：知识聚合拥有的当前表及查询索引；项目表先由 Workspace 建立。
SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_documents(
 id TEXT PRIMARY KEY,project_id TEXT REFERENCES workspace_projects(id),title TEXT NOT NULL,
 digest TEXT NOT NULL,bytes INTEGER NOT NULL,archived INTEGER NOT NULL DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS workspace_chunks(
 document_id TEXT REFERENCES workspace_documents(id),chunk_index INTEGER,content TEXT NOT NULL,
 PRIMARY KEY(document_id,chunk_index));
CREATE INDEX IF NOT EXISTS workspace_documents_project ON workspace_documents(project_id,archived);
"""


class SqliteKnowledgeRepository:
    """每实例复用所属 Runtime 连接；返回来源数据，不能借检索结果扩大权限。"""

    def __init__(self, runtime, *, project_lookup, vector_index=None):
        """装配原始对象、项目只读端口和可选向量索引；构造时原子建立知识表。"""
        # runtime：不可变对象库的装配入口；文档原始字节不塞入 SQLite。
        self.runtime = runtime
        # store：与 Conversation 准入共用的连接；数据库事务不包含对象或向量写入。
        self.store = runtime.store
        # project_lookup：仅核对项目身份的只读调用；知识仓储不能修改项目。
        self.project_lookup = project_lookup
        # vector_index：可丢弃重建的派生召回后端；SQLite 摘要、归档和作用域仍为真相。
        self.vector_index = vector_index
        self.store.ensure_schema(SCHEMA)

    # 读取可见知识文档及 chunk 数；project 过滤决定检索范围。
    def documents(self, project_id=None):
        return [
            dict(r)
            for r in self.store.db.execute(
                "SELECT d.*,p.name project_name,(SELECT count(*) FROM workspace_chunks c WHERE c.document_id=d.id) chunks "
                "FROM workspace_documents d LEFT JOIN workspace_projects p ON p.id=d.project_id "
                "WHERE d.archived=0 AND (? IS NULL OR d.project_id=?) ORDER BY d.rowid DESC",
                (project_id, project_id),
            )
        ]

    # 先发布 UTF-8 不可变对象，再同事务保存文档和 chunks；发布后 DB 失败只留下未引用对象。
    def admission_revision(self, project_id=None):
        """纯 SQL 返回可见候选版本，供 Turn 准备/提交 CAS；不访问对象或派生向量服务。"""
        rows = self.store.db.execute(
            "SELECT id,project_id,title,digest,bytes FROM workspace_documents "
            "WHERE archived=0 AND (project_id IS NULL OR project_id=?) ORDER BY id", (project_id,)
        ).fetchall()
        return digest_json([dict(row) for row in rows])

    # 先发布 UTF-8 不可变对象，再同事务保存文档和 chunks；发布后 DB 失败只留下未引用对象。
    def import_document(self, value):
        title = str(value.get("title", "")).strip()
        text = value.get("content", "")
        if (
            not title
            or len(title) > 200
            or not isinstance(text, str)
            or not text.strip()
            or len(text.encode("utf-8")) > 1_000_000
        ):
            raise ValueError("document requires title and UTF-8 text up to 1 MB")
        pid = value.get("project_id") or None
        if pid:
            self.project_lookup(pid)
        digest = self.runtime.objects.put(text.encode("utf-8"))
        did = f"doc_{uuid.uuid4().hex}"
        # 分片只计算一次；SQLite 写入和返回计数共享同一结果，避免重复分配整份文档的切片。
        parts = chunks(text)
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO workspace_documents(id,project_id,title,digest,bytes) VALUES(?,?,?,?,?)",
                (did, pid, title, digest, len(text.encode("utf-8"))),
            )
            db.executemany(
                "INSERT INTO workspace_chunks VALUES(?,?,?)",
                [(did, i, part) for i, part in enumerate(parts)],
            )
        result = {
            "id": did,
            "title": title,
            "digest": digest,
            "chunks": len(parts),
        }
        # 向量索引是事务外可重建投影；失败不能回滚已经成功提交的权威文档。
        self._sync_document_vector(did)
        return result

    # 把一个已提交文档的当前 chunks 幂等投影到向量库；失败返回状态而不篡改 SQLite 事实。
    def _sync_document_vector(self, document_id):
        if self.vector_index is None:
            return {"configured": False, "synced": 0}
        document = self.document(document_id)
        rows = self.store.db.execute(
            "SELECT chunk_index,content FROM workspace_chunks WHERE document_id=? ORDER BY chunk_index",
            (document_id,),
        ).fetchall()
        payload = [
            {
                "record_id": f"doc:{document_id}:{int(row['chunk_index'])}",
                "source_version": document["digest"],
                "text": document["title"] + "\n" + row["content"],
                "document_id": document_id,
                "chunk_index": int(row["chunk_index"]),
                "project_id": document.get("project_id") or "",
            }
            for row in rows
        ]
        try:
            result = self.vector_index.sync_knowledge(payload)
            return {"configured": True, "synced": result.get("upserted", 0)}
        except RuntimeError:
            return {"configured": True, "synced": 0, "degraded": True}

    # 显式重建当前可见知识的派生向量索引；调用方可在安装/迁移后运行，失败不影响词面检索。
    def rebuild_vector_index(self, project_id=None):
        if self.vector_index is None:
            return {"configured": False, "documents": 0, "synced": 0}
        documents = self.documents(project_id)
        synced = 0
        degraded = False
        for document in documents:
            result = self._sync_document_vector(document["id"])
            synced += int(result.get("synced") or 0)
            degraded = degraded or bool(result.get("degraded"))
        return {
            "configured": True,
            "documents": len(documents),
            "synced": synced,
            "degraded": degraded,
        }

    # 按保存摘要读取完整文档对象；对象库校验字节身份，归档状态由调用者判断。
    def document(self, did):
        row = self.store.db.execute(
            "SELECT * FROM workspace_documents WHERE id=?", (did,)
        ).fetchone()
        if not row:
            raise KeyError(did)
        return {
            **dict(row),
            "content": self.runtime.objects.get(row["digest"]).decode("utf-8"),
        }

    def chunk_page(self, document_id, *, cursor=0, limit=12):
        """读取一页分片导航，多取一项判断后续页；游标是分片编号，不是字符偏移。

        文档作用域由执行适配器先核对，SQL 与分片布局仅由知识仓储拥有。
        文档内容不可原地修改，因此分页持续绑定同一 document/digest。
        """
        if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("L1 cursor must be non-negative and limit must be 1-20 chunks")
        rows = self.store.db.execute(
            "SELECT chunk_index,content FROM workspace_chunks WHERE document_id=? AND chunk_index>=? "
            "ORDER BY chunk_index LIMIT ?", (document_id, cursor, limit + 1),
        ).fetchall()
        values = [{"chunk_index": int(row["chunk_index"]), "preview": row["content"][:500],
                   "citation": f"doc:{document_id}:{row['chunk_index']}"} for row in rows[:limit]]
        has_more = len(rows) > limit
        return {"chunks": values, "cursor": cursor, "has_more": has_more,
                "next_cursor": values[-1]["chunk_index"] + 1 if values and has_more else None}

    # 把文档从未来检索集合撤下；不删除冻结快照引用的原始对象。
    def archive_document(self, did):
        self.document(did)
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute("UPDATE workspace_documents SET archived=1 WHERE id=?", (did,))
        return {"id": did}

    def knowledge_candidates(self, project_id=None, *, cursor=0, page_size=512):
        """按 SQLite rowid 分页扫描所有可见 chunk；cursor 是候选覆盖位置，不是相关度分数。"""
        if type(cursor) is not int or cursor < 0:
            raise ValueError("cursor must be a non-negative integer")
        if type(page_size) is not int or not 1 <= page_size <= 2000:
            raise ValueError("page_size must be 1-2000")
        rows = self.store.db.execute(
            "SELECT c.rowid AS candidate_cursor,c.document_id,c.chunk_index,c.content,"
            "d.title,d.digest FROM workspace_chunks c "
            "JOIN workspace_documents d ON d.id=c.document_id "
            "WHERE c.rowid>? AND d.archived=0 AND (d.project_id IS NULL OR d.project_id=?) "
            "ORDER BY c.rowid LIMIT ?",
            (cursor, project_id, page_size + 1),
        ).fetchall()
        values = [dict(row) for row in rows[:page_size]]
        has_more = len(rows) > page_size
        next_cursor = values[-1]["candidate_cursor"] if values else cursor
        return {
            "candidates": values,
            "cursor": cursor,
            "next_cursor": next_cursor,
            "has_more": has_more,
        }

    # 遍历全可见候选后保留有界 top-k，报告 scanned/matched/pages；不能在排序前用 LIMIT 静默丢候选。
    def _lexical_search_report(self, query, project_id=None, limit=5):
        # SQL 游标遍历全部可见块，内存只留 top-k 候选；先 LIMIT 会让后面的高分来源永远不可见。
        if not isinstance(query, str) or len(query) > 1000:
            raise ValueError("query up to 1000 characters")
        if type(limit) is not int or not 1 <= limit <= 8:
            raise ValueError("limit must be 1-8")
        cursor = 0
        scanned = 0
        matched_count = 0
        pages = 0
        top = []
        while True:
            page = self.knowledge_candidates(project_id, cursor=cursor, page_size=512)
            pages += 1
            for item in page["candidates"]:
                scanned += 1
                scored = score_chunk(query, item)
                if scored is None:
                    continue
                matched_count += 1
                top.append(scored)
                if len(top) > limit * 4:
                    top = sorted(
                        top,
                        key=lambda value: (
                            -value["score"],
                            value["document_id"],
                            value["chunk_index"],
                        ),
                    )[:limit]
            cursor = page["next_cursor"]
            if not page["has_more"]:
                break
        sources = sorted(
            top,
            key=lambda value: (
                -value["score"],
                value["document_id"],
                value["chunk_index"],
            ),
        )[:limit]
        for source in sources:
            source.pop("candidate_cursor", None)
        return {
            "sources": sources,
            "retrieval": {
                "backend": "local-lexical",
                "candidate_policy": "all-visible-chunks-v2",
                "scanned": scanned,
                "matched": matched_count,
                "pages": pages,
                "exhausted": True,
                "truncated_before_ranking": False,
            },
        }

    # 先以词面全覆盖建立可靠基线，再按可选 Milvus 候选做 RRF；每个向量命中必须回 SQLite 校验版本/作用域。
    def search_report(self, query, project_id=None, limit=5):
        lexical = self._lexical_search_report(query, project_id, limit)
        if self.vector_index is None or not str(query).strip():
            return lexical
        try:
            # 首次启用 Milvus 时补齐已有文档；适配器按 source version 幂等跳过本进程已同步项。
            self.rebuild_vector_index(project_id)
            hits = self.vector_index.search_knowledge(
                str(query), limit=max(32, int(limit) * 8)
            )
        except RuntimeError:
            lexical["retrieval"]["vector_status"] = "unavailable"
            lexical["retrieval"]["degraded"] = True
            return lexical

        vector_rows = []
        stale_rejected = 0
        for hit in hits:
            record_id = str(hit.get("record_id") or "")
            parts = record_id.split(":")
            if len(parts) != 3 or parts[0] != "doc":
                stale_rejected += 1
                continue
            try:
                chunk_index = int(parts[2])
            except ValueError:
                stale_rejected += 1
                continue
            row = self.store.db.execute(
                "SELECT c.document_id,c.chunk_index,c.content,d.title,d.digest,d.project_id,d.archived "
                "FROM workspace_chunks c JOIN workspace_documents d ON d.id=c.document_id "
                "WHERE c.document_id=? AND c.chunk_index=?",
                (parts[1], chunk_index),
            ).fetchone()
            if (
                row is None
                or int(row["archived"])
                or row["project_id"] not in {None, project_id}
                or str(row["digest"]) != str(hit.get("source_version") or "")
            ):
                stale_rejected += 1
                continue
            item = dict(row)
            item.pop("archived", None)
            item.pop("project_id", None)
            item["citation"] = f"doc:{item['document_id']}:{item['chunk_index']}"
            item["vector_distance"] = hit.get("distance")
            vector_rows.append(item)

        lexical_rows = list(lexical["sources"])
        identity = lambda item: f"{item['document_id']}:{int(item['chunk_index'])}"
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
        sources = []
        for key, item in merged.items():
            item["hybrid_score"] = round(rrf.get(key, 0.0), 8)
            sources.append(item)
        sources.sort(
            key=lambda item: (
                -float(item.get("hybrid_score") or 0.0),
                item["document_id"],
                int(item["chunk_index"]),
            )
        )
        sources = sources[:limit]
        return {
            "sources": sources,
            "retrieval": {
                **lexical["retrieval"],
                "backend": "lexical+milvus",
                "candidate_policy": "lexical-full-cover+milvus-hydrated-rrf-v1",
                "vector_candidates": len(hits),
                "vector_hydrated": len(vector_rows),
                "vector_stale_rejected": stale_rejected,
                "vector_status": "ready",
                "degraded": False,
            },
        }

    # 读取当前作用域的检索结果；相似度只用于排序，不升级为已验证事实。
    def search(self, query, project_id=None, limit=5):
        return self.search_report(query, project_id, limit)["sources"]
