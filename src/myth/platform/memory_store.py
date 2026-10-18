"""生产记忆的持久 SQLite 适配器。
以 kind/source_ref 去重并递增 revision；原子维护 SQLite 词项倒排索引生成候选，最终来源真相仍由权威 Memory 决定。
"""

from __future__ import annotations

import json
import re
import uuid
from contextlib import nullcontext
from typing import Any, Iterable, Mapping

from ..domain import IdentityConflict, digest_json
from .continuity import CURRENT_FACTS_POLICY
from .memory import MemoryKind
from .memory_lifecycle import (
    MemoryDeltaError,
    apply_text_delta,
    evaluate_freshness,
    evaluate_support_closure,
    evidence_json,
    normalize_delta_operations,
    normalize_evidence_set,
    normalize_memory_actions,
)
from .support_paths import evaluate_alternative_closure, normalize_proof_paths
from .retrieval import reciprocal_rank_scores
from .memory_recall import build_recall_plan, parse_memory_ref, rank_probe_rows


# SCHEMA：本仓储拥有的当前表、索引与约束；由 Store 原子初始化，不叠加旧格式迁移。
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

CREATE TABLE IF NOT EXISTS workspace_memory_evidence(
    memory_id TEXT NOT NULL REFERENCES workspace_memories(memory_id),
    evidence_ref TEXT NOT NULL,
    source_memory_id TEXT,
    source_revision INTEGER,
    quote TEXT NOT NULL DEFAULT '',
    relevance TEXT NOT NULL DEFAULT '',
    occurred_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(memory_id, evidence_ref)
);

CREATE TABLE IF NOT EXISTS workspace_memory_revisions(
    memory_id TEXT NOT NULL REFERENCES workspace_memories(memory_id),
    revision INTEGER NOT NULL,
    text TEXT NOT NULL,
    fact_level TEXT NOT NULL,
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(memory_id, revision)
);

CREATE TABLE IF NOT EXISTS workspace_memory_changes(
    change_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL REFERENCES workspace_memories(memory_id),
    revision INTEGER NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT,
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_workspace_memory_changes_scope
    ON workspace_memory_changes(scope_type, scope_id, change_seq);

-- 索引仅存预分词的候选身份；文本/revision/scope/active 仍由 workspace_memories 裁决。
CREATE TABLE IF NOT EXISTS workspace_memory_terms(
    memory_id TEXT NOT NULL REFERENCES workspace_memories(memory_id),
    term TEXT NOT NULL,
    PRIMARY KEY(memory_id,term)
);
CREATE INDEX IF NOT EXISTS idx_workspace_memory_terms_term
    ON workspace_memory_terms(term,memory_id);
CREATE TABLE IF NOT EXISTS workspace_memory_terms_state(
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    last_change_seq INTEGER NOT NULL CHECK(last_change_seq>=-1)
);

-- 非 Myth 写路径一旦直接修改 Memory 行，立即使派生索引失效。
-- 正常 Memory Store 在同一事务的 _record_change() 之后恢复为已覆盖水位。
CREATE TRIGGER IF NOT EXISTS trg_memory_terms_insert_dirty
AFTER INSERT ON workspace_memories BEGIN
    UPDATE workspace_memory_terms_state SET last_change_seq=-1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS trg_memory_terms_update_dirty
AFTER UPDATE ON workspace_memories BEGIN
    UPDATE workspace_memory_terms_state SET last_change_seq=-1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS trg_memory_terms_delete_dirty
AFTER DELETE ON workspace_memories BEGIN
    UPDATE workspace_memory_terms_state SET last_change_seq=-1 WHERE singleton=1;
END;

-- 只有显式受信任准入的 Memory 才拥有可替代的 AND 证明组；原有 Memory 保持严格 All-of。
CREATE TABLE IF NOT EXISTS workspace_memory_proof_paths(
    memory_id TEXT PRIMARY KEY REFERENCES workspace_memories(memory_id),
    owner_revision INTEGER NOT NULL CHECK(owner_revision>=1),
    evidence_digest TEXT NOT NULL,
    paths_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_memory_proof_path_revisions(
    memory_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    paths_json TEXT NOT NULL,
    PRIMARY KEY(memory_id,revision),
    FOREIGN KEY(memory_id,revision) REFERENCES workspace_memory_revisions(memory_id,revision)
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
        # 本进程索引缓存只代表某个 Adapter 已覆盖的 SQLite 变化水位；进程重启必须重新核对。
        self._vector_backfilled_adapter = None
        # _vector_backfilled_change_seq：索引已成功覆盖的权威变化水位，异常和撤销不能冒充健康进度。
        self._vector_backfilled_change_seq: int | None = None
        self.store.ensure_schema(SCHEMA)
        self._ensure_terms_current()

    # 启动只在权威水位与派生索引水位不一致时重建，且全程短 SQLite 写事务；
    # 任意中断都不会公开半更新索引，既有 Memory 数据保持不变。
    def _ensure_terms_current(self) -> None:
        row = self.store.db.execute(
            "SELECT last_change_seq FROM workspace_memory_terms_state WHERE singleton=1"
        ).fetchone()
        if row is not None and int(row[0]) == self.current_change_seq():
            return
        with self.store.tx() as db:
            current = self.current_change_seq()
            row = db.execute(
                "SELECT last_change_seq FROM workspace_memory_terms_state WHERE singleton=1"
            ).fetchone()
            if row is not None and int(row[0]) == current:
                return
            db.execute("DELETE FROM workspace_memory_terms")
            for item in db.execute(
                "SELECT memory_id,text FROM workspace_memories WHERE active=1"
            ).fetchall():
                db.executemany(
                    "INSERT INTO workspace_memory_terms(memory_id,term) VALUES (?,?)",
                    [(str(item["memory_id"]), term) for term in sorted(_terms(str(item["text"])))],
                )
            db.execute(
                "INSERT INTO workspace_memory_terms_state(singleton,last_change_seq) VALUES (1,?) "
                "ON CONFLICT(singleton) DO UPDATE SET last_change_seq=excluded.last_change_seq",
                (current,),
            )

    # 每次权威变更与索引投影同事务；如果写入失败，正文、Revision 与水位全部回滚。
    def _sync_terms(self, db, memory_id: str, change_seq: int) -> None:
        row = db.execute(
            "SELECT text,active FROM workspace_memories WHERE memory_id=?", (memory_id,)
        ).fetchone()
        if row is None:
            raise KeyError(memory_id)
        db.execute("DELETE FROM workspace_memory_terms WHERE memory_id=?", (memory_id,))
        if bool(row["active"]):
            db.executemany(
                "INSERT INTO workspace_memory_terms(memory_id,term) VALUES (?,?)",
                [(memory_id, term) for term in sorted(_terms(str(row["text"])))],
            )
        db.execute(
            "INSERT INTO workspace_memory_terms_state(singleton,last_change_seq) VALUES (1,?) "
            "ON CONFLICT(singleton) DO UPDATE SET last_change_seq=excluded.last_change_seq",
            (change_seq,),
        )

    # 校验 kind/text/source/scope/fact_level/evidence 后按来源更新或创建；revision 与证据快照同事务提交。
    def remember(
        self,
        *,
        kind: str | MemoryKind,
        text: str,
        source_ref: str,
        scope_type: str = "global",
        scope_id: str | None = None,
        fact_level: str = "context",
        evidence: Iterable[Mapping[str, Any]] | None = None,
        _db=None,
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

        # 所有 Memory 写入口共用此事务准入；不能只依赖模型批量 Action 的调用方校验。
        with self.store.transaction_scope(_db) as db:
            row = db.execute(
                "SELECT * FROM workspace_memories WHERE kind=? AND source_ref=?",
                (memory_kind.value, source),
            ).fetchone()
            memory_id = str(row["memory_id"]) if row else f"mem_{uuid.uuid4().hex}"
            revision = int(row["revision"]) + 1 if row else 1

            # 修改作用域但未显式替换 Evidence 时，也要对仍保留的引用按目标范围复核。
            prepared = (
                self._prepare_evidence(db, evidence, default_ref=source)
                if evidence is not None or row is None
                else self._evidence_rows(db, memory_id)
            )
            self._check_action_evidence_scope(
                db,
                {"memory_id": memory_id, "scope_type": scope, "scope_id": scope_value},
                prepared,
            )
            if row:
                # 正文或 Evidence 一旦演化，旧 Proof 声明不得无声继承到新 Revision。
                db.execute("DELETE FROM workspace_memory_proof_paths WHERE memory_id=?", (memory_id,))
                db.execute(
                    "UPDATE workspace_memories SET text=?,scope_type=?,scope_id=?,fact_level=?,"
                    "revision=?,active=1,updated_at=CURRENT_TIMESTAMP WHERE memory_id=?",
                    (value, scope, scope_value, level, revision, memory_id),
                )
                if evidence is not None:
                    self._replace_evidence(db, memory_id, prepared)
            else:
                db.execute(
                    "INSERT INTO workspace_memories(memory_id,kind,text,source_ref,scope_type,scope_id,fact_level) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (memory_id, memory_kind.value, value, source, scope, scope_value, level),
                )
                self._replace_evidence(db, memory_id, prepared)

            # 持久提交前验证整个支持图；多跳循环、旧 revision 或深度超限统一回滚。
            if self.freshness(memory_id)["is_stale"]:
                raise MemoryDeltaError("memory evidence support closure is invalid")
            self._snapshot_revision(db, memory_id)
            self._record_change(db, memory_id)
            if row and (row["scope_type"], row["scope_id"]) != (scope, scope_value):
                # Scope 迁移同时通知旧范围，避免刷新只关注新范围而沿用旧派生结论。
                self._record_change(
                    db, memory_id, scope=(str(row["scope_type"]), row["scope_id"])
                )

        record = self.get(memory_id)
        # 外部向量索引不是同一事务；只有最外层提交后才同步，内部事务协作者负责在提交后调用。
        if _db is None:
            self._sync_vector_record(record)
        return record


    # _prepare_evidence：在写事务内把 source_memory_id 固定到当时 revision，外部 ref 保持显式来源。
    def _prepare_evidence(
        self,
        db,
        values: Iterable[Mapping[str, Any]] | None,
        *,
        default_ref: str | None = None,
    ) -> list[dict[str, Any]]:
        prepared = normalize_evidence_set(values, default_ref=default_ref)
        result: list[dict[str, Any]] = []
        for item in prepared:
            value = dict(item)
            source_memory_id = value.get("source_memory_id")
            if source_memory_id:
                row = db.execute(
                    "SELECT memory_id,revision FROM workspace_memories WHERE memory_id=?",
                    (source_memory_id,),
                ).fetchone()
                if row is None:
                    raise MemoryDeltaError(
                        f"source memory does not exist: {source_memory_id}"
                    )
                value["source_revision"] = int(row["revision"])
                if not value.get("evidence_ref"):
                    value["evidence_ref"] = f"memory:{source_memory_id}"
            else:
                value["source_revision"] = None
            result.append(value)
        return result

    # _evidence_rows：当前证据只读投影；revision snapshot 另存 JSON，避免历史指向可变当前表。
    def _evidence_rows(self, db, memory_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in db.execute(
                "SELECT evidence_ref,source_memory_id,source_revision,quote,relevance,occurred_at "
                "FROM workspace_memory_evidence WHERE memory_id=? ORDER BY evidence_ref",
                (memory_id,),
            ).fetchall()
        ]

    # _replace_evidence：当前 Evidence 是 Memory revision 的一部分；整组替换发生在同一 SQLite 事务。
    def _replace_evidence(
        self, db, memory_id: str, values: Iterable[Mapping[str, Any]]
    ) -> None:
        db.execute(
            "DELETE FROM workspace_memory_evidence WHERE memory_id=?", (memory_id,)
        )
        for item in values:
            db.execute(
                "INSERT INTO workspace_memory_evidence("
                "memory_id,evidence_ref,source_memory_id,source_revision,quote,relevance,occurred_at"
                ") VALUES (?,?,?,?,?,?,?)",
                (
                    memory_id,
                    item["evidence_ref"],
                    item.get("source_memory_id"),
                    item.get("source_revision"),
                    item.get("quote") or "",
                    item.get("relevance") or "",
                    item.get("occurred_at"),
                ),
            )

    # _proof_paths_for：只接受与当前 revision 和整套 Evidence 完全一致的组声明，手工 SQL 篡改 fail closed。
    def _proof_paths_for(self, db, memory_id: str, row, evidence) -> tuple[object | None, str | None]:
        stored = db.execute(
            "SELECT owner_revision,evidence_digest,paths_json "
            "FROM workspace_memory_proof_paths WHERE memory_id=?",
            (memory_id,),
        ).fetchone()
        if stored is None:
            return None, None
        if int(stored["owner_revision"]) != int(row["revision"]):
            return None, "proof_paths_revision_changed"
        if stored["evidence_digest"] != digest_json(list(evidence)):
            return None, "proof_paths_evidence_changed"
        try:
            paths = json.loads(stored["paths_json"])
            normalize_proof_paths(paths, evidence)
        except (ValueError, TypeError, MemoryDeltaError):
            return None, "proof_paths_invalid"
        return paths, None

    # _snapshot_revision：把当前正文/事实等级/active/evidence 固化为不可变 revision 行；同 revision 不覆盖。
    def _snapshot_revision(self, db, memory_id: str) -> None:
        row = db.execute(
            "SELECT memory_id,revision,text,fact_level,active FROM workspace_memories WHERE memory_id=?",
            (memory_id,),
        ).fetchone()
        if row is None:
            raise KeyError(memory_id)
        evidence = self._evidence_rows(db, memory_id)
        db.execute(
            "INSERT OR IGNORE INTO workspace_memory_revisions("
            "memory_id,revision,text,fact_level,active,evidence_json"
            ") VALUES (?,?,?,?,?,?)",
            (
                memory_id,
                int(row["revision"]),
                str(row["text"]),
                str(row["fact_level"]),
                int(row["active"]),
                evidence_json(evidence),
            ),
        )
        proof = db.execute(
            "SELECT paths_json FROM workspace_memory_proof_paths "
            "WHERE memory_id=? AND owner_revision=?",
            (memory_id, int(row["revision"])),
        ).fetchone()
        if proof is not None:
            db.execute(
                "INSERT OR IGNORE INTO workspace_memory_proof_path_revisions("
                "memory_id,revision,paths_json) VALUES (?,?,?)",
                (memory_id, int(row["revision"]), str(proof["paths_json"])),
            )

    # _record_change：每次已提交 revision 追加单调水位；派生 Mental Model 用它判断 scope 是否出现新变化。
    def _record_change(
        self, db, memory_id: str, *, scope: tuple[str, str | None] | None = None
    ) -> int:
        row = db.execute(
            "SELECT memory_id,revision,scope_type,scope_id,active FROM workspace_memories WHERE memory_id=?",
            (memory_id,),
        ).fetchone()
        if row is None:
            raise KeyError(memory_id)
        cursor = db.execute(
            "INSERT INTO workspace_memory_changes(memory_id,revision,scope_type,scope_id,active) "
            "VALUES (?,?,?,?,?)",
            (
                memory_id,
                int(row["revision"]),
                scope[0] if scope else str(row["scope_type"] or "global"),
                scope[1] if scope else row["scope_id"],
                int(row["active"]),
            ),
        )
        change_seq = int(cursor.lastrowid)
        # 一份权威变化水位推动唯一派生词项索引，外部向量库不参与本地提交。
        if scope is None:
            self._sync_terms(db, memory_id, change_seq)
        else:
            db.execute(
                "UPDATE workspace_memory_terms_state SET last_change_seq=? WHERE singleton=1",
                (change_seq,),
            )
        return change_seq

    # current_change_seq：返回当前 Memory Domain 的持久变化水位；零表示尚无已记录变化。
    def current_change_seq(self) -> int:
        row = self.store.db.execute(
            "SELECT COALESCE(MAX(change_seq),0) AS seq FROM workspace_memory_changes"
        ).fetchone()
        return int(row["seq"] if row else 0)

    # continuity_facts：只对当前可见 user_asserted/verified 状态做版本摘要；检索分数和正文不进入 Turn 绑定。
    def continuity_facts(
        self,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        rows = self.store.db.execute(
            "SELECT memory_id,revision,fact_level,scope_type,scope_id,text "
            "FROM workspace_memories WHERE active=1 "
            "AND fact_level IN ('user_asserted','verified') ORDER BY memory_id"
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            if not self._visible(item, project_id, session_id):
                continue
            items.append(
                {
                    "memory_id": item["memory_id"],
                    "revision": int(item["revision"]),
                    "fact_level": item["fact_level"],
                    "scope_type": item["scope_type"],
                    "scope_id": item["scope_id"],
                    "content_digest": digest_json(str(item["text"])),
                }
            )
        return {
            "policy": CURRENT_FACTS_POLICY,
            "count": len(items),
            "digest": digest_json(items),
        }

    # changes_since：按可见作用域读取水位后的变化身份；只用于派生 freshness，不把 change log 当正文。
    def changes_since(
        self,
        change_seq: int,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
        limit: int = 1000,
        exclude_memory_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if type(change_seq) is not int or change_seq < 0:
            raise ValueError("change_seq must be a non-negative integer")
        if type(limit) is not int or not 1 <= limit <= 5000:
            raise ValueError("limit must be 1-5000")
        rows = self.store.db.execute(
            "SELECT * FROM workspace_memory_changes WHERE change_seq>? "
            "AND (scope_type='global' OR (scope_type='project' AND scope_id=?) "
            "OR (scope_type='session' AND scope_id=?)) "
            "AND (? IS NULL OR memory_id<>?) "
            "ORDER BY change_seq LIMIT ?",
            (change_seq, project_id, session_id, exclude_memory_id, exclude_memory_id, limit),
        ).fetchall()
        # limit 约束可见且非自身的变化；不可见/自身事件不能遮挡后续真实变更。
        return [dict(row) for row in rows]

    # evidence：返回当前 revision 的证据链；Evidence 证明来源，不等同 Verification。
    def evidence(self, memory_id: str) -> list[dict[str, Any]]:
        self.get(memory_id)
        return self._evidence_rows(self.store.db, memory_id)

    # revision_snapshot：读取不可变历史 revision；缺失代表当时未记录，不能用当前内容补造历史。
    def revision_snapshot(self, memory_id: str, revision: int) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM workspace_memory_revisions WHERE memory_id=? AND revision=?",
            (memory_id, int(revision)),
        ).fetchone()
        if row is None:
            raise KeyError(f"{memory_id}@{revision}")
        value = dict(row)
        value["evidence"] = json.loads(value.pop("evidence_json"))
        history = self.store.db.execute(
            "SELECT paths_json FROM workspace_memory_proof_path_revisions "
            "WHERE memory_id=? AND revision=?",
            (memory_id, int(revision)),
        ).fetchone()
        if history is not None:
            value["proof_paths"] = json.loads(history["paths_json"])
        return value

    # declare_proof_paths：只允许可信操作者将多个完整 AND 组登记为可替代的 OR，拒绝模型自行认证。
    def declare_proof_paths(
        self, memory_id: str, paths: list[list[str]] | tuple[tuple[str, ...], ...],
        *, expected_revision: int,
    ) -> dict[str, Any]:
        """组的变更就是 Memory 新 Revision；更新、证明与水位均在同一 SQLite 事务提交。"""
        if type(expected_revision) is not int or expected_revision < 1:
            raise MemoryDeltaError("proof paths require positive expected_revision")
        with self.store.tx() as db:
            # 步骤一：在写锁内核对 CAS 与 active 身份，任何旧调用不能覆盖当前证明。
            row = db.execute(
                "SELECT * FROM workspace_memories WHERE memory_id=?", (memory_id,),
            ).fetchone()
            if row is None:
                raise KeyError(memory_id)
            if int(row["revision"]) != expected_revision:
                raise MemoryDeltaError("proof paths expected_revision mismatch")
            if not bool(row["active"]):
                raise MemoryDeltaError("cannot declare proof paths on revoked memory")
            # Proof 结构有效不等于完成独立验收；不能降低已验证/用户断言事实的证明门槛。
            if str(row["fact_level"]) != "context":
                raise MemoryDeltaError("proof paths require context fact_level; stronger facts need independent verification")
            evidence = self._evidence_rows(db, memory_id)
            groups = normalize_proof_paths(paths, evidence)
            previous, error = self._proof_paths_for(db, memory_id, row, evidence)
            if error is None and previous is not None and tuple(map(tuple, previous)) == groups:
                return dict(row)
            updated_revision = int(row["revision"]) + 1
            db.execute(
                "UPDATE workspace_memories SET revision=?,updated_at=CURRENT_TIMESTAMP WHERE memory_id=?",
                (updated_revision, memory_id),
            )
            db.execute(
                "INSERT INTO workspace_memory_proof_paths(memory_id,owner_revision,evidence_digest,paths_json) "
                "VALUES (?,?,?,?) ON CONFLICT(memory_id) DO UPDATE SET "
                "owner_revision=excluded.owner_revision,evidence_digest=excluded.evidence_digest,"
                "paths_json=excluded.paths_json",
                (memory_id, updated_revision, digest_json(evidence), json.dumps(groups, separators=(",", ":"))),
            )
            if self.freshness(memory_id)["is_stale"]:
                raise MemoryDeltaError("proof paths do not establish a valid support closure")
            self._snapshot_revision(db, memory_id)
            self._record_change(db, memory_id)
        result = self.get(memory_id)
        self._sync_vector_record(result)
        return result

    # freshness：只对 Memory-linked evidence 比较当前 source revision/active；外部 provenance 无水位时保持 untracked。
    def freshness(self, memory_id: str) -> dict[str, Any]:
        # 读取前先冻结单连接 WAL 快照；写事务或 Recall 已有快照时复用，不发生嵌套。
        snapshot = nullcontext(self.store.db) if self.store.db.in_transaction else self.store.read_snapshot()
        with snapshot:
            evidence = self.evidence(memory_id)
            source_ids = {
                str(item["source_memory_id"])
                for item in evidence
                if item.get("source_memory_id")
            }
            current: dict[str, dict[str, Any] | None] = {}
            for source_id in source_ids:
                row = self.store.db.execute(
                    "SELECT memory_id,revision,active FROM workspace_memories WHERE memory_id=?",
                    (source_id,),
                ).fetchone()
                current[source_id] = None if row is None else dict(row)
            direct = evaluate_freshness(evidence, current)
            # 统一 SQLite WAL 快照读完整关系；仅遇显式 Proof Paths 才切换到 OR-of-AND。
            root_row = self.get(memory_id)
            # 常规工作区没有任何替代证明时，仅一条索引式 EXISTS 查询，保持旧闭包的热路径成本。
            # 不缓存跨连接布尔值：其他 Writer 新增 Proof 时必须在本次 WAL 快照可见。
            proof_enabled = self.store.db.execute(
                "SELECT 1 FROM workspace_memory_proof_paths LIMIT 1"
            ).fetchone() is not None
            root_paths, root_error = (
                self._proof_paths_for(self.store.db, memory_id, root_row, evidence)
                if proof_enabled else (None, None)
            )
            if root_paths is not None:
                root_row["_proof_paths"] = root_paths
            if root_error:
                root_row["_proof_paths_error"] = root_error
            any_paths = root_paths is not None or bool(root_error)

            # 读取每个来源时保留其证明元数据：祖先的替代证明也必须参与递归维护。
            def load(source_id: str):
                nonlocal any_paths
                row = self.store.db.execute(
                    "SELECT memory_id,revision,active,scope_type,scope_id "
                    "FROM workspace_memories WHERE memory_id=?", (source_id,),
                ).fetchone()
                if row is None:
                    return None, ()
                source = dict(row)
                dependencies = self._evidence_rows(self.store.db, source_id)
                paths, error = (
                    self._proof_paths_for(self.store.db, source_id, source, dependencies)
                    if proof_enabled else (None, None)
                )
                if paths is not None:
                    source["_proof_paths"] = paths
                if error:
                    source["_proof_paths_error"] = error
                any_paths = any_paths or paths is not None or bool(error)
                return source, dependencies

            # 默认继续原始严格闭包，避免对未 opt-in 的 Memory 悄然改语义。
            closure = evaluate_support_closure(
                memory_id, root_row, evidence, load=load,
            )
            if any_paths:
                closure = evaluate_alternative_closure(
                    memory_id, root_row, evidence, load=load,
                )
                # Revoked 路径可以失效，只有完整替代路径存活才允许保持 fresh。
                # 越权/循环/检查不完整依然直接 stale，不可因另一路成立而豁免。
                direct["stale_sources"] = closure["stale_sources"]
                direct["is_stale"] = bool(closure["stale_sources"])
                direct["status"] = (
                    "stale" if direct["is_stale"] else
                    ("fresh" if direct["linked_sources"] else "untracked")
                )
                direct["proof_paths"] = {
                    "declared": root_paths is not None,
                    # Proof 解释必须能从 winning index 回到原始 Evidence refs，不能只报告数量。
                    "paths": list(root_paths or ()),
                    "valid_path_indices": list(closure["valid_paths"]),
                    "failed_paths": closure["failed_paths"],
                }
            elif closure["stale_sources"]:
                direct["status"] = "stale"
                direct["is_stale"] = True
                direct["stale_sources"] = closure["stale_sources"]
            direct["support_closure"] = {
                "checked_memories": closure["checked_memories"],
                "checked_edges": closure["checked_edges"],
                "valid": not bool(closure["stale_sources"]),
            }
            return direct

    # apply_delta：CAS 与 revision/evidence/change_seq 在同一 SQLite 事务内提交；内部协作者负责最外层向量同步。
    def apply_delta(
        self,
        memory_id: str,
        operations: Iterable[Mapping[str, Any]],
        *,
        expected_revision: int,
        _db=None,
    ) -> dict[str, Any]:
        """按冻结 revision 更新正文/证据；失败整项回滚，内部事务不提前发布向量副作用。"""
        if type(expected_revision) is not int or expected_revision < 1:
            raise MemoryDeltaError("memory delta requires a positive integer expected_revision")
        normalized = normalize_delta_operations(operations)
        # 步骤一：即使空操作，也在事务内核对身份和预期 revision；不能用陈旧快照伪装无变化成功。
        with self.store.transaction_scope(_db) as db:
            row = db.execute(
                "SELECT * FROM workspace_memories WHERE memory_id=?", (memory_id,),
            ).fetchone()
            if row is None:
                raise KeyError(memory_id)
            if int(row["revision"]) != expected_revision:
                raise MemoryDeltaError(
                    "memory delta expected_revision does not match current revision"
                )
            if not bool(row["active"]):
                raise MemoryDeltaError("memory delta cannot mutate a revoked memory")
            if not normalized:
                return dict(row)

            current_evidence = self._evidence_rows(db, memory_id)
            by_ref = {str(item["evidence_ref"]): dict(item) for item in current_evidence}
            new_text = apply_text_delta(str(row["text"]), normalized)

            # 步骤二：证据增删以证据身份为键，先校验所有操作，再一次性替换当前快照。
            for operation in normalized:
                if operation["op"] == "add_evidence":
                    prepared = self._prepare_evidence(db, [operation["evidence"]])[0]
                    ref = str(prepared["evidence_ref"])
                    if ref in by_ref:
                        raise MemoryDeltaError(f"memory evidence already exists: {ref}")
                    by_ref[ref] = prepared
                elif operation["op"] == "remove_evidence":
                    ref = str(operation["evidence_ref"])
                    if ref not in by_ref:
                        raise MemoryDeltaError(f"memory evidence does not exist: {ref}")
                    del by_ref[ref]

            # Delta 的直接使用与 Action 批处理同一 Evidence 准入；旧引用不得隐式跨 scope。
            self._check_action_evidence_scope(db, dict(row), by_ref.values())

            # 步骤三：正文、Evidence、immutable revision 和变化水位必须同生共死。
            revision = int(row["revision"]) + 1
            db.execute(
                "UPDATE workspace_memories SET text=?,revision=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE memory_id=?",
                (new_text, revision, memory_id),
            )
            self._replace_evidence(db, memory_id, [by_ref[key] for key in sorted(by_ref)])
            # 新正文/证据不得重用旧版本的替代证明准入；回到默认 All-of。
            db.execute("DELETE FROM workspace_memory_proof_paths WHERE memory_id=?", (memory_id,))
            # 统一复核多跳依赖；在同一 SQLite 事务内完成，不会留下半次 Delta。
            if self.freshness(memory_id)["is_stale"]:
                raise MemoryDeltaError("memory evidence support closure is invalid")
            self._snapshot_revision(db, memory_id)
            self._record_change(db, memory_id)

        record = self.get(memory_id)
        if _db is None:
            self._sync_vector_record(record)
        return record

    # _check_action_evidence_scope：防止批处理把私有来源嵌入更宽的 Memory 可见范围；本地权威来源才可被引用。
    def _check_action_evidence_scope(self, db, target: Mapping[str, Any], evidence) -> None:
        """外部 evidence_ref 不声称可验证的作用域；引用 Memory 时必须全局或同一精确范围。"""
        for entry in evidence:
            source_id = entry.get("source_memory_id")
            if not source_id:
                continue
            # 来源不能以当前记忆本身为独立证明；这种闭环在 revision 推进后必定失效。
            if source_id == target.get("memory_id"):
                raise MemoryDeltaError("memory action cannot cite itself as evidence")
            row = db.execute(
                "SELECT scope_type,scope_id,active FROM workspace_memories WHERE memory_id=?",
                (source_id,),
            ).fetchone()
            if row is None or not bool(row["active"]):
                raise MemoryDeltaError("memory action references unavailable source memory")
            if row["scope_type"] != "global" and (
                row["scope_type"] != target["scope_type"]
                or row["scope_id"] != target["scope_id"]
            ):
                raise MemoryDeltaError("memory action evidence crosses a narrower scope")

    # apply_actions：ADD/UPDATE/DELETE 组成单个持久提交；CAS 防重放，冲突要求 reconcile 而不是盲重试。
    def apply_actions(
        self,
        actions: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    ) -> dict[str, Any]:
        """一次提交最多 16 个 Memory Action；结果只能说明本地持久状态，不能授权模型/工具效果。"""
        normalized = normalize_memory_actions(actions)
        if not normalized:
            return {"status": "NOOP", "count": 0, "changes": [], "change_seq": self.current_change_seq()}
        changes = []
        # 步骤一：同连接 BEGIN IMMEDIATE 保护 ADD 唯一性、UPDATE/DELETE 版本与全批回滚。
        with self.store.tx() as db:
            for item in normalized:
                op = item["op"]
                if op == "ADD":
                    conflict = db.execute(
                        "SELECT memory_id FROM workspace_memories WHERE kind=? AND source_ref=?",
                        (item["kind"], item["source_ref"]),
                    ).fetchone()
                    if conflict is not None:
                        raise MemoryDeltaError("memory ADD identity already exists; reconcile before retry")
                    self._check_action_evidence_scope(db, item, item["evidence"])
                    record = self.remember(
                        kind=item["kind"], text=item["text"],
                        source_ref=item["source_ref"],
                        scope_type=item["scope_type"], scope_id=item["scope_id"],
                        fact_level="context", evidence=item["evidence"], _db=db,
                    )
                elif op == "UPDATE":
                    row = db.execute(
                        "SELECT scope_type,scope_id FROM workspace_memories WHERE memory_id=?",
                        (item["memory_id"],),
                    ).fetchone()
                    if row is None:
                        raise KeyError(item["memory_id"])
                    linked = (
                        operation["evidence"]
                        for operation in item["operations"]
                        if operation["op"] == "add_evidence"
                    )
                    self._check_action_evidence_scope(db, {
                        "memory_id": item["memory_id"],
                        "scope_type": row["scope_type"], "scope_id": row["scope_id"],
                    }, linked)
                    record = self.apply_delta(
                        item["memory_id"], item["operations"],
                        expected_revision=item["expected_revision"], _db=db,
                    )
                else:
                    record = self.revoke(
                        item["memory_id"],
                        expected_revision=item["expected_revision"], _db=db,
                    )
                changes.append({
                    "op": op, "memory_id": record["memory_id"],
                    "revision": int(record["revision"]), "active": bool(record["active"]),
                })
            seq = self.current_change_seq()

        # 步骤二：提交后再同步可重建的向量投影；任何外部索引异常不得重放已经成功的 SQLite 决定。
        projections = []
        for entry in changes:
            if not entry["active"]:
                continue
            record = self.get(entry["memory_id"])
            try:
                result = self._sync_vector_record(record)
            except Exception as exc:
                result = {
                    "configured": self.vector_index is not None,
                    "degraded": True, "reason": type(exc).__name__,
                }
            projections.append({
                "memory_id": entry["memory_id"], **result,
            })
        return {
            "status": "COMMITTED",
            "count": len(changes),
            "changes": changes,
            "change_seq": seq,
            "vector_projections": projections,
        }

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
        except Exception as exc:
            # 权威 Memory 已独立提交；派生索引的网络/驱动异常只产生退化事实，不能触发盲目重放。
            return {
                "configured": True, "synced": 0, "degraded": True,
                "reason": type(exc).__name__,
            }

    # 显式重建 active Memory 的派生向量索引；安装/迁移后可调用，失败不改变任何记忆事实。
    def rebuild_vector_index(self) -> dict:
        # 不在远端 I/O 期间持 SQLite 事务；冻结扫描之前的水位，后续并发写入会强制下一次重新核对。
        observed_change_seq = self.current_change_seq()
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
        if not degraded:
            # 标记只能在完整且无已知退化的补建后推进；写端产生的新水位下次仍会触发补建。
            self._vector_backfilled_adapter = self.vector_index
            self._vector_backfilled_change_seq = observed_change_seq
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
        exclude_source_prefix: str | None = None,
    ) -> dict:
        if type(cursor) is not int or cursor < 0:
            raise ValueError("cursor must be a non-negative integer")
        # rowid游标按原始页推进，过滤scope/kind/派生来源不改变分页覆盖。
        # 每页报告原始scanned与has_more，调用方遍历全部候选后排名，避免限页制造漏召回。
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
            if exclude_source_prefix and str(item["source_ref"]).startswith(exclude_source_prefix):
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

    # Query Selectivity：仅遍历 query 的倒排候选，不扫描每条记忆正文；
    # 词项使用与旧逻辑相同的 English/CJK bigram，因此保持精确 Overlap 和稳定并列次序。
    def _lexical_search_report(
        self,
        query: str,
        *,
        kinds: Iterable[str | MemoryKind] | None = None,
        limit: int = 6,
        project_id: str | None = None,
        session_id: str | None = None,
        exclude_source_prefix: str | None = None,
    ) -> dict:
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("limit must be 1-20")
        terms = sorted(_terms(str(query)))
        opts = dict(
            kinds=kinds, limit=limit, project_id=project_id,
            session_id=session_id, exclude_source_prefix=exclude_source_prefix,
        )
        # 已有进程可能仍采用旧写实现；若权威水位领先索引，正确性优先，退回全扫描。
        index = self.store.db.execute(
            "SELECT last_change_seq FROM workspace_memory_terms_state WHERE singleton=1"
        ).fetchone()
        if not terms or index is None or int(index[0]) != self.current_change_seq():
            fallback = self._lexical_scan_report(query, **opts)
            fallback["retrieval"]["degraded"] = bool(terms)
            fallback["retrieval"]["degraded_reason"] = (
                "lexical_index_stale" if terms else "no_indexable_terms"
            )
            return fallback
        allowed = None
        if kinds is not None:
            allowed = {
                item.value if isinstance(item, MemoryKind) else MemoryKind(str(item)).value
                for item in kinds
            }
        sql = (
            "SELECT m.rowid AS candidate_cursor,m.*,COUNT(*) AS overlap,COUNT(*) OVER() AS matched_total "
            "FROM workspace_memory_terms AS t "
            "JOIN workspace_memories AS m ON m.memory_id=t.memory_id "
            f"WHERE t.term IN ({','.join('?' for _ in terms)}) AND m.active=1 "
            "AND (m.scope_type='global' "
            "OR (m.scope_type='project' AND m.scope_id=?) "
            "OR (m.scope_type='session' AND m.scope_id=?)) "
        )
        params: list[Any] = [*terms, project_id, session_id]
        if allowed:
            sql += f"AND m.kind IN ({','.join('?' for _ in allowed)}) "
            params.extend(sorted(allowed))
        if exclude_source_prefix:
            # Prefix 不能交给 LIKE 通配符解释，避免 '%' 和 '_' 导致越界排除。
            sql += "AND substr(m.source_ref,1,?)<>? "
            params.extend((len(exclude_source_prefix), exclude_source_prefix))
        sql += "GROUP BY m.memory_id ORDER BY overlap DESC,candidate_cursor DESC,m.memory_id LIMIT ?"
        params.append(limit)
        selected = self.store.db.execute(sql, params).fetchall()
        memories = []
        matched_total = int(selected[0]["matched_total"]) if selected else 0
        for row in selected:
            value = dict(row)
            value.pop("candidate_cursor", None)
            value.pop("overlap", None)
            value.pop("matched_total", None)
            memories.append(value)
        return {
            "memories": memories,
            "retrieval": {
                "backend": "memory-term-index",
                "candidate_policy": "indexed-lexical-exact-overlap-v1",
                # COUNT OVER 统计经权限筛选后真正匹配的 Memory 数量，非全部可见行；
                # 查询仍须访问候选 posting，不能把 returned 伪装成总成本。
                "scanned": matched_total,
                "visible": matched_total,
                "matched": matched_total,
                "pages": 0,
                "exhausted": True,
                "truncated_before_ranking": False,
                "index_terms": len(terms),
                "matching_candidate_count": matched_total,
                "returned": len(memories),
            },
        }

    # 遍历所有可见候选后稳定排 top-k，返回扫描覆盖；Memory 内容只作上下文。
    def _lexical_scan_report(
        self,
        query: str,
        *,
        kinds: Iterable[str | MemoryKind] | None = None,
        limit: int = 6,
        project_id: str | None = None,
        session_id: str | None = None,
        exclude_source_prefix: str | None = None,
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
                exclude_source_prefix=exclude_source_prefix,
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
                "backend": "memory-lexical-fallback",
                "candidate_policy": "full-visible-scan-when-index-unavailable",
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
        exclude_source_prefix: str | None = None,
    ) -> dict:
        lexical = self._lexical_search_report(
            query,
            kinds=kinds,
            limit=limit,
            project_id=project_id,
            session_id=session_id,
            exclude_source_prefix=exclude_source_prefix,
        )
        if self.vector_index is None or not str(query).strip():
            return lexical

        allowed = None
        if kinds is not None:
            allowed = {
                item.value if isinstance(item, MemoryKind) else MemoryKind(str(item)).value
                for item in kinds
            }
        backfill_cached = False
        backfill_degraded = False
        try:
            # 同一 Adapter 且 SQLite 无新变化时跳过全库补建；变更/进程重启/后端失健康则重新核对。
            index_status = self.vector_index.status()
            backfill_cached = (
                self._vector_backfilled_adapter is self.vector_index
                and self._vector_backfilled_change_seq == self.current_change_seq()
                and bool(index_status.get("healthy", True))
            )
            if not backfill_cached:
                backfill = self.rebuild_vector_index()
                backfill_degraded = bool(backfill.get("degraded", False))
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
                or (
                    exclude_source_prefix
                    and str(item["source_ref"]).startswith(exclude_source_prefix)
                )
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
                "vector_status": "backfill_degraded" if backfill_degraded else "ready",
                "vector_backfill_cached": backfill_cached,
                "degraded": backfill_degraded,
            },
        }

    # recall_report：多探针只选候选；required_refs 必须按作用域、active、revision、来源 freshness 独立核验。
    # 缺失引用不被其他相似片段填补；报告是 Evidence gate 而非生成答案的充分性证明。
    def recall_report(
        self,
        query: str,
        *,
        probes: Iterable[str] | None = None,
        required_refs: Iterable[str] | None = None,
        limit: int = 6,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        plan = build_recall_plan(
            query, probes=probes, required_refs=required_refs, limit=limit,
        )
        rankings = []
        probe_reports = []
        for probe in plan.queries:
            report = self.search_report(
                probe, limit=min(20, max(plan.limit * 2, 8)),
                project_id=project_id, session_id=session_id,
            )
            rankings.append(report["memories"])
            # 不复制正文到报告，也不将不可比较的检索分数称为置信度。
            probe_reports.append({
                "query": probe,
                "backend": report["retrieval"]["backend"],
                "matched": report["retrieval"].get("matched"),
                "returned": len(report["memories"]),
                "degraded": bool(report["retrieval"].get("degraded", False)),
            })

        ranked = rank_probe_rows(rankings)
        required_rows = []
        invalid_refs = []
        invalid_ids = set()
        rejected_candidates = 0

        # 步骤一：检索/向量调用全部已结束；在一个短 WAL 读快照内统一核验来源、作用域与版本。
        # 这样不会将不同提交时刻的 revision/evidence 拼成“已锚定”，同时不持写锁等待外部后端。
        with self.store.read_snapshot() as db:
            for ref in plan.required_refs:
                memory_id, revision = parse_memory_ref(ref)
                invalid_ids.add(memory_id)
                row = db.execute(
                    "SELECT * FROM workspace_memories WHERE memory_id=?", (memory_id,),
                ).fetchone()
                if row is None:
                    invalid_refs.append({"ref": ref, "reason": "missing"})
                    continue
                item = dict(row)
                if not item["active"] or not self._visible(item, project_id, session_id):
                    invalid_refs.append({"ref": ref, "reason": "unavailable"})
                    continue
                if int(item["revision"]) != revision:
                    invalid_refs.append({"ref": ref, "reason": "revision_changed"})
                    continue
                if self.freshness(memory_id)["is_stale"]:
                    invalid_refs.append({"ref": ref, "reason": "stale_evidence"})
                    continue
                required_rows.append(item)
                invalid_ids.discard(memory_id)

            # 步骤二：指定来源优先；普通排名候选必须再次 hydration，不能返回查询期间已变更的旧片段。
            by_id = {str(item["memory_id"]): item for item in required_rows}
            for ranked_item in ranked:
                key = str(ranked_item["memory_id"])
                if key in invalid_ids or key in by_id:
                    continue
                if len(by_id) >= plan.limit:
                    break
                row = db.execute(
                    "SELECT * FROM workspace_memories WHERE memory_id=?", (key,),
                ).fetchone()
                if (
                    row is None
                    or not bool(row["active"])
                    or not self._visible(dict(row), project_id, session_id)
                    or int(row["revision"]) != int(ranked_item["revision"])
                ):
                    rejected_candidates += 1
                    continue
                if self.freshness(key)["is_stale"]:
                    rejected_candidates += 1
                    continue
                by_id[key] = dict(row)
            views = [
                self.resolve(
                    memory_id, resolution="L0",
                    project_id=project_id, session_id=session_id,
                )
                for memory_id in by_id
            ]

        return {
            "memories": views,
            "evidence_gate": {
                "status": "references_unavailable" if invalid_refs else (
                    "anchored" if plan.required_refs else "unverified"
                ),
                "required_refs": len(plan.required_refs),
                "valid_refs": len(required_rows),
                "invalid_refs": invalid_refs,
                "answer_verified": False,
            },
            "retrieval": {
                "backend": "bounded-multi-probe",
                "probes": probe_reports,
                "unique_candidates": len(ranked),
                "selected": len(views),
                "snapshot_validated": True,
                "candidate_rejected_after_search": rejected_candidates,
                "degraded": any(item["degraded"] for item in probe_reports),
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
        # 显式 L0/L1/L2 解析同样必须冻结当前行、证据与支持闭包，不许跨提交拼接正文。
        snapshot = nullcontext(self.store.db) if self.store.db.in_transaction else self.store.read_snapshot()
        with snapshot:
            item = self.get(str(memory_id))
            if not item.get("active") or not self._visible(item, project_id, session_id):
                raise PermissionError("memory is not visible in the admitted scope")
            level = str(resolution or "L2").upper()
            if level not in {"L0", "L1", "L2"}:
                raise ValueError("resolution must be L0/L1/L2")
            text = str(item.get("text") or "")
            stable_ref = f"memory:{item['memory_id']}@{item['revision']}"
            evidence = self.evidence(str(item["memory_id"]))
            freshness = self.freshness(str(item["memory_id"]))
            # 旧库坏引用仍可报告为 stale，但不能通过显式 resolve 泄露不允许的私有血缘。
            if any(
                entry["reason"] in {"scope_violation", "missing", "proof_paths_invalid", "proof_paths_evidence_changed", "proof_paths_revision_changed"}
                for entry in freshness["stale_sources"]
            ):
                raise PermissionError("memory provenance is not visible in the admitted scope")
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
                "proof_count": len(evidence),
                "freshness": freshness["status"],
                "is_stale": freshness["is_stale"],
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
            return {
                **base,
                "text": text,
                "bytes": len(text.encode("utf-8")),
                "evidence": evidence,
                "freshness_report": freshness,
            }

    # 模型上下文只接纳复核过的 L0 Memory；原始 search_report 可保留候选供诊断。
    def search_view_report(
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
        # 检索发生在快照外，避免远端索引请求长期占用 SQLite WAL 读事务。
        # 有界超额取候选可在过期证据占据前排时补足结果，但不声称穷尽所有有效记录。
        report = self.search_report(
            query,
            kinds=kinds,
            limit=min(20, max(limit, limit * 3)),
            project_id=project_id,
            session_id=session_id,
        )
        views = []
        rejected = 0
        snapshot = nullcontext(self.store.db) if self.store.db.in_transaction else self.store.read_snapshot()
        with snapshot:
            for item in report["memories"]:
                if len(views) >= limit:
                    break
                memory_id = str(item["memory_id"])
                current = self.store.db.execute(
                    "SELECT revision,active,scope_type,scope_id FROM workspace_memories WHERE memory_id=?",
                    (memory_id,),
                ).fetchone()
                if (
                    current is None
                    or not bool(current["active"])
                    or int(current["revision"]) != int(item["revision"])
                    or not self._visible(dict(current), project_id, session_id)
                ):
                    rejected += 1
                    continue
                try:
                    view = self.resolve(
                        memory_id, resolution="L0",
                        project_id=project_id, session_id=session_id,
                    )
                except (KeyError, PermissionError):
                    rejected += 1
                    continue
                if view["is_stale"]:
                    rejected += 1
                    continue
                views.append(view)
        return {
            "memories": views,
            "retrieval": {
                **report["retrieval"],
                "resolution": "L0",
                "snapshot_validated": True,
                "candidate_rejected_after_search": rejected,
            },
        }

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

    # revoke：DELETE 只产生新 tombstone revision，旧证据/历史不销毁；批处理可要求精确 expected_revision。
    def revoke(self, memory_id: str, *, expected_revision: int | None = None, _db=None) -> dict:
        """在本地权威事务内撤销未来可见性；显式 CAS 冲突不能吞掉或冒充成功。"""
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise MemoryDeltaError("memory revoke requires a positive integer expected_revision")
        # 确认当前 revision、active 与撤销写入均在同一事务内，避免与另一连接竞争。
        with self.store.transaction_scope(_db) as db:
            row = db.execute(
                "SELECT * FROM workspace_memories WHERE memory_id=?", (memory_id,),
            ).fetchone()
            if row is None:
                raise KeyError(memory_id)
            if expected_revision is not None and int(row["revision"]) != expected_revision:
                raise MemoryDeltaError("memory revoke expected_revision does not match current revision")
            if not bool(row["active"]):
                if expected_revision is not None:
                    raise MemoryDeltaError("memory was already revoked; reconcile before retry")
                return dict(row)
            db.execute("DELETE FROM workspace_memory_proof_paths WHERE memory_id=?", (memory_id,))
            db.execute(
                "UPDATE workspace_memories SET active=0,revision=revision+1,"
                "updated_at=CURRENT_TIMESTAMP WHERE memory_id=?",
                (memory_id,),
            )
            self._snapshot_revision(db, memory_id)
            self._record_change(db, memory_id)
        return self.get(memory_id)

    # record_episode：同 Run 的经历正文必须完全一致；补偿重放不能增加 revision 或令其他派生记忆伪过期。
    def record_episode(self, run_id: str, user_text: str, assistant_text: str) -> dict:
        """保存唯一的终态经历；同源同内容直接返回，身份冲突显式拒绝以便调用方核对事实。"""
        text = f"User: {user_text.strip()}\nAssistant: {assistant_text.strip()}"
        if len(text.encode("utf-8")) > 8_000:
            text = text.encode("utf-8")[:8_000].decode("utf-8", errors="ignore")
        row = self.store.db.execute(
            "SELECT session_id,snapshot_json FROM workspace_turns WHERE run_id=?",
            (run_id,),
        ).fetchone()
        # Episode 的 Scope 属于本 Run 准入时冻结的项目；会话后续改项目不能把历史搬进新项目。
        frozen = json.loads(row["snapshot_json"]) if row else {}
        project = frozen.get("project") if isinstance(frozen, dict) else None
        project_id = project.get("id") if isinstance(project, dict) else None
        scope_type = "project" if project_id else "session"
        scope_id = project_id or (row["session_id"] if row else run_id)
        source = f"run:{run_id}"
        # 同一 BEGIN IMMEDIATE 内检查唯一来源、快照与新建；不能跨连接先查后写产生竞争。
        with self.store.tx() as db:
            existing = db.execute(
                "SELECT * FROM workspace_memories WHERE kind=? AND source_ref=?",
                (MemoryKind.EPISODIC.value, source),
            ).fetchone()
            if existing is not None:
                if (
                    bool(existing["active"])
                    and existing["text"] == text
                    and existing["scope_type"] == scope_type
                    and existing["scope_id"] == scope_id
                    and existing["fact_level"] == "context"
                ):
                    return dict(existing)
                raise IdentityConflict(
                    "the recorded run episode conflicts with its committed immutable source"
                )
            record = self.remember(
                kind=MemoryKind.EPISODIC,
                text=text,
                source_ref=source,
                scope_type=scope_type,
                scope_id=scope_id,
                fact_level="context",
                _db=db,
            )
        # SQLite 已经提交后才同步可重建向量投影；外部索引与 Memory 事实不可混为一笔事务。
        self._sync_vector_record(record)
        return record
