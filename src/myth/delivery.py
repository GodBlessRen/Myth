"""Conversation 交付账本：终态收尾、验收、工作项和人工关注。
该模块只保存可核对事实，不把模型的“完成”自述升级为验收；终态收尾用持久义务补齐 Memory/Goal 投影。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .domain import canonical_json


ACCEPTANCE_STATES = {"UNVERIFIED", "PASSED", "FAILED", "INCONCLUSIVE"}
WORK_ITEM_STATES = {"PLANNED", "RUNNING", "WAITING", "BLOCKED", "DONE", "INVALIDATED"}
ATTENTION_KINDS = {"setup", "clarification", "review", "rework", "recovery"}

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS delivery_finalizations(
    run_id TEXT PRIMARY KEY NOT NULL REFERENCES workspace_turns(run_id),
    state TEXT NOT NULL,
    answer TEXT NOT NULL,
    goal_id TEXT,
    goal_summary TEXT NOT NULL DEFAULT '',
    next_action TEXT NOT NULL DEFAULT '',
    waiting_for TEXT NOT NULL DEFAULT '',
    memory_done INTEGER NOT NULL DEFAULT 0 CHECK(memory_done IN (0,1)),
    goal_done INTEGER NOT NULL DEFAULT 0 CHECK(goal_done IN (0,1)),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS delivery_acceptance(
    run_id TEXT PRIMARY KEY NOT NULL REFERENCES workspace_turns(run_id),
    state TEXT NOT NULL DEFAULT 'UNVERIFIED',
    subject_digest TEXT NOT NULL,
    checker_id TEXT NOT NULL DEFAULT 'conversation/manual',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    note TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS delivery_work_items(
    work_item_id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL REFERENCES workspace_turns(run_id),
    goal_id TEXT,
    ordinal INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_revision INTEGER NOT NULL DEFAULT 1,
    input_digest TEXT NOT NULL DEFAULT '',
    dependencies_json TEXT NOT NULL DEFAULT '[]',
    acceptance_state TEXT NOT NULL DEFAULT 'UNVERIFIED',
    acceptance_json TEXT NOT NULL DEFAULT '{}',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    budget_json TEXT NOT NULL DEFAULT '{}',
    progress_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, ordinal)
);
CREATE INDEX IF NOT EXISTS delivery_work_items_run
ON delivery_work_items(run_id, ordinal);
CREATE TABLE IF NOT EXISTS delivery_attention(
    attention_id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL REFERENCES workspace_turns(run_id),
    kind TEXT NOT NULL,
    seconds INTEGER NOT NULL CHECK(seconds >= 0),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS delivery_attention_run
ON delivery_attention(run_id);
"""


# 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


# 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
def _bounded_json(value: Any, *, max_bytes: int = 32_000) -> str:
    raw = canonical_json(value)
    if len(raw.encode("utf-8")) > max_bytes:
        raise ValueError("delivery JSON exceeds configured size limit")
    return raw


# 该类型集中拥有当前职责，避免把状态真相分散到多个适配器。
class DeliveryLedger:
    """拥有交付事实；运行执行权仍属于原 Conversation/Control/Runtime。"""

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def __init__(self, runtime, *, sota_route=None) -> None:
        # 持有当前协作对象；生命周期与所属 Runtime/仓储一致。
        self.runtime = runtime
        # 持有当前协作对象；生命周期与所属 Runtime/仓储一致。
        self.store = runtime.store
        # sota_route：验收通过后才同步成功路径；失败/撤销会取消比较资格。
        self.sota_route = sota_route
        self.store.db.executescript(SCHEMA)

    # 下列辅助入口保持边界显式，调用不隐式扩大权限或真实性。
    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def prepare_completion(
        self,
        run_id: str,
        answer: str,
        *,
        goal_id: str | None = None,
        goal_summary: str = "",
        next_action: str = "",
        waiting_for: str = "",
    ) -> dict[str, Any]:
        """回答提交前先保存收尾义务；崩溃后由已提交回答事实决定是否补齐。"""
        text = str(answer or "")
        if not text or len(text.encode("utf-8")) > 64_000:
            raise ValueError("completion answer must contain 1-64000 UTF-8 bytes")
        with self.store.tx() as db:
            row = db.execute(
                "SELECT state FROM delivery_finalizations WHERE run_id=?", (run_id,)
            ).fetchone()
            if row and row["state"] == "DONE":
                return self.finalization(run_id)
            db.execute(
                "INSERT INTO delivery_finalizations("
                "run_id,state,answer,goal_id,goal_summary,next_action,waiting_for"
                ") VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET "
                "state='PREPARED',answer=excluded.answer,goal_id=excluded.goal_id,"
                "goal_summary=excluded.goal_summary,next_action=excluded.next_action,"
                "waiting_for=excluded.waiting_for,last_error=NULL,updated_at=CURRENT_TIMESTAMP",
                (
                    run_id,
                    "PREPARED",
                    text,
                    goal_id,
                    str(goal_summary)[:4000],
                    str(next_action)[:4000],
                    str(waiting_for)[:4000],
                ),
            )
        return self.finalization(run_id)

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def mark_answer_committed(self, run_id: str) -> dict[str, Any]:
        with self.store.tx() as db:
            db.execute(
                "UPDATE delivery_finalizations SET state='PENDING',last_error=NULL,"
                "updated_at=CURRENT_TIMESTAMP WHERE run_id=? AND state='PREPARED'",
                (run_id,),
            )
        return self.finalization(run_id)

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def finalization(self, run_id: str) -> dict[str, Any] | None:
        row = self.store.db.execute(
            "SELECT * FROM delivery_finalizations WHERE run_id=?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def _subject(self, run_id: str) -> tuple[str, list[Any]]:
        answer_row = self.store.db.execute(
            "SELECT content,metadata_json FROM workspace_messages "
            "WHERE run_id=? AND role='assistant' ORDER BY rowid DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        answer = answer_row["content"] if answer_row else ""
        evidence: list[Any] = []
        if answer_row:
            metadata = json.loads(answer_row["metadata_json"])
            for item in metadata.get("citations") or []:
                if isinstance(item, dict):
                    ref = item.get("citation") or item.get("source_ref") or item.get("document_id")
                    if ref:
                        evidence.append(ref)
                elif isinstance(item, str):
                    evidence.append(item)
        artifacts = []
        for row in self.store.db.execute(
            "SELECT decision_id,result_json FROM workspace_operations "
            "WHERE run_id=? AND state='RESOLVED' ORDER BY rowid",
            (run_id,),
        ).fetchall():
            result = json.loads(row["result_json"]) if row["result_json"] else {}
            if result.get("evidence_ref"):
                evidence.append(result["evidence_ref"])
            artifact = result.get("artifact")
            if artifact:
                artifacts.append(
                    {
                        "decision_id": row["decision_id"],
                        "name": artifact.get("name"),
                        "digest": artifact.get("digest"),
                        "bytes": artifact.get("bytes"),
                    }
                )
        subject = {"run_id": run_id, "answer": answer, "artifacts": artifacts}
        deduped = []
        seen = set()
        for item in evidence:
            key = canonical_json(item)
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return _digest(subject), deduped[:100]

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def ensure_acceptance(
        self, run_id: str, subject_digest: str | None = None, evidence: list[Any] | None = None
    ) -> dict[str, Any]:
        current_digest, current_evidence = self._subject(run_id)
        digest = subject_digest or current_digest
        if digest != current_digest:
            raise ValueError("acceptance subject digest must match current delivery")
        evidence = current_evidence if evidence is None else evidence
        raw_evidence = _bounded_json(evidence, max_bytes=48_000)
        with self.store.tx() as db:
            row = db.execute(
                "SELECT * FROM delivery_acceptance WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO delivery_acceptance("
                    "run_id,state,subject_digest,checker_id,evidence_json,note"
                    ") VALUES(?,?,?,?,?,?)",
                    (
                        run_id,
                        "UNVERIFIED",
                        digest,
                        "conversation/manual",
                        raw_evidence,
                        "Conversation answer completed; semantic acceptance has not been claimed.",
                    ),
                )
            elif row["subject_digest"] != digest:
                db.execute(
                    "UPDATE delivery_acceptance SET state='UNVERIFIED',subject_digest=?,"
                    "checker_id='delivery/subject-change',evidence_json=?,"
                    "note='Delivery subject changed; previous acceptance invalidated.',"
                    "revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                    (digest, raw_evidence, run_id),
                )
            elif row["state"] == "UNVERIFIED" and raw_evidence != row["evidence_json"]:
                db.execute(
                    "UPDATE delivery_acceptance SET evidence_json=?,updated_at=CURRENT_TIMESTAMP "
                    "WHERE run_id=?",
                    (raw_evidence, run_id),
                )
        return self.acceptance(run_id)

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def acceptance(self, run_id: str) -> dict[str, Any] | None:
        row = self.store.db.execute(
            "SELECT * FROM delivery_acceptance WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            return None
        value = dict(row)
        value["evidence"] = json.loads(value.pop("evidence_json"))
        return value

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def set_acceptance(
        self,
        run_id: str,
        *,
        state: str,
        checker_id: str,
        evidence: list[Any] | None = None,
        note: str = "",
        subject_digest: str | None = None,
    ) -> dict[str, Any]:
        mapping = {"PASS": "PASSED", "FAIL": "FAILED"}
        target = mapping.get(str(state).upper(), str(state).upper())
        if target not in ACCEPTANCE_STATES:
            raise ValueError("acceptance state must be UNVERIFIED/PASSED/FAILED/INCONCLUSIVE")
        checker = str(checker_id or "").strip()
        if not checker or len(checker) > 200:
            raise ValueError("checker_id must contain 1-200 characters")
        current_digest, default_evidence = self._subject(run_id)
        if subject_digest is not None and subject_digest != current_digest:
            raise ValueError("stale acceptance subject digest")
        raw_evidence = _bounded_json(
            default_evidence if evidence is None else evidence, max_bytes=48_000
        )
        message = str(note or "")
        if len(message.encode("utf-8")) > 8_000:
            raise ValueError("acceptance note exceeds 8000 UTF-8 bytes")
        with self.store.tx() as db:
            row = db.execute(
                "SELECT * FROM delivery_acceptance WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO delivery_acceptance("
                    "run_id,state,subject_digest,checker_id,evidence_json,note"
                    ") VALUES(?,?,?,?,?,?)",
                    (run_id, target, current_digest, checker, raw_evidence, message),
                )
            else:
                db.execute(
                    "UPDATE delivery_acceptance SET state=?,subject_digest=?,checker_id=?,"
                    "evidence_json=?,note=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP "
                    "WHERE run_id=?",
                    (target, current_digest, checker, raw_evidence, message, run_id),
                )
            db.execute(
                "UPDATE delivery_work_items SET acceptance_state=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE run_id=?",
                (target, run_id),
            )
        accepted = self.acceptance(run_id)
        if self.sota_route is not None:
            # SOTA Route 只消费显式验收事实；同步失败必须可见，不能伪装已学习。
            self.sota_route.sync_acceptance(
                run_id,
                accepted["state"],
                subject_digest=accepted["subject_digest"],
            )
        return accepted

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def ensure_root_work_item(self, turn: dict[str, Any]) -> dict[str, Any]:
        run_id = turn["run_id"]
        goal = (turn.get("snapshot") or {}).get("goal") or {}
        messages = (turn.get("snapshot") or {}).get("messages") or []
        title = "Deliver current turn"
        for message in reversed(messages):
            if message.get("role") == "user" and str(message.get("content") or "").strip():
                title = str(message["content"]).strip().replace("\n", " ")[:180]
                break
        with self.store.tx() as db:
            db.execute(
                "INSERT OR IGNORE INTO delivery_work_items("
                "work_item_id,run_id,goal_id,ordinal,title,status,plan_revision,input_digest,"
                "dependencies_json,acceptance_json,budget_json"
                ") VALUES(?,?,?,?,?,'RUNNING',1,?,'[]',?,'{}')",
                (
                    self._id("work"),
                    run_id,
                    goal.get("goal_id"),
                    1,
                    title,
                    str(turn.get("entry_digest") or ""),
                    canonical_json(
                        {
                            "kind": "conversation_delivery",
                            "rule": "answer completion is separate from semantic acceptance",
                        }
                    ),
                ),
            )
        return self.work_items(run_id)[0]

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def work_items(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.store.db.execute(
            "SELECT * FROM delivery_work_items WHERE run_id=? ORDER BY ordinal",
            (run_id,),
        ).fetchall()
        values = []
        for row in rows:
            item = dict(row)
            for key in ("dependencies_json", "acceptance_json", "evidence_json", "budget_json"):
                item[key.removesuffix("_json")] = json.loads(item.pop(key))
            values.append(item)
        return values

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def plan_work_items(
        self, run_id: str, items: list[dict[str, Any]], *, plan_revision: int | None = None
    ) -> list[dict[str, Any]]:
        if not isinstance(items, list) or not 1 <= len(items) <= 24:
            raise ValueError("work item plan must contain 1-24 items")
        row = self.store.db.execute(
            "SELECT max(plan_revision) FROM delivery_work_items WHERE run_id=?", (run_id,)
        ).fetchone()
        current = int(row[0] or 0)
        revision = current + 1 if plan_revision is None else int(plan_revision)
        if revision <= current:
            raise ValueError("plan revision must increase")
        start = self.store.db.execute(
            "SELECT coalesce(max(ordinal),0) FROM delivery_work_items WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        prepared = []
        for offset, item in enumerate(items, start=1):
            title = str(item.get("title") or "").strip()
            if not title or len(title) > 200:
                raise ValueError("work item title must contain 1-200 characters")
            prepared.append(
                (
                    self._id("work"),
                    run_id,
                    item.get("goal_id"),
                    int(start) + offset,
                    title,
                    "PLANNED",
                    revision,
                    str(item.get("input_digest") or ""),
                    _bounded_json(item.get("dependencies") or [], max_bytes=8_000),
                    _bounded_json(item.get("acceptance") or {}, max_bytes=16_000),
                    _bounded_json(item.get("budget") or {}, max_bytes=8_000),
                )
            )
        with self.store.tx() as db:
            db.executemany(
                "INSERT INTO delivery_work_items("
                "work_item_id,run_id,goal_id,ordinal,title,status,plan_revision,input_digest,"
                "dependencies_json,acceptance_json,budget_json"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                prepared,
            )
        return self.work_items(run_id)

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def update_work_item(
        self,
        work_item_id: str,
        *,
        status: str | None = None,
        progress_note: str | None = None,
        evidence: list[Any] | None = None,
    ) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM delivery_work_items WHERE work_item_id=?", (work_item_id,)
        ).fetchone()
        if not row:
            raise KeyError(work_item_id)
        target = row["status"] if status is None else str(status).upper()
        if target not in WORK_ITEM_STATES:
            raise ValueError("invalid work item state")
        note = row["progress_note"] if progress_note is None else str(progress_note)
        if len(note.encode("utf-8")) > 8_000:
            raise ValueError("work item progress note exceeds 8000 UTF-8 bytes")
        raw_evidence = (
            row["evidence_json"]
            if evidence is None
            else _bounded_json(evidence, max_bytes=48_000)
        )
        with self.store.tx() as db:
            db.execute(
                "UPDATE delivery_work_items SET status=?,progress_note=?,evidence_json=?,"
                "updated_at=CURRENT_TIMESTAMP WHERE work_item_id=?",
                (target, note, raw_evidence, work_item_id),
            )
        return next(item for item in self.work_items(row["run_id"]) if item["work_item_id"] == work_item_id)

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def update_root_work_item(
        self,
        run_id: str,
        *,
        status: str,
        progress_note: str = "",
        evidence: list[Any] | None = None,
    ) -> None:
        row = self.store.db.execute(
            "SELECT work_item_id FROM delivery_work_items WHERE run_id=? AND ordinal=1",
            (run_id,),
        ).fetchone()
        if row:
            self.update_work_item(
                row["work_item_id"], status=status, progress_note=progress_note, evidence=evidence
            )

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def record_tool_result(self, run_id: str, result: dict[str, Any]) -> None:
        items = self.work_items(run_id)
        if not items:
            return
        root = items[0]
        evidence = list(root["evidence"])
        ref = result.get("evidence_ref")
        if ref:
            evidence.append(ref)
        if result.get("capability_id") == "test.run":
            evidence.append(
                {
                    "kind": "test",
                    "status": result.get("status"),
                    "profile_id": result.get("profile_id"),
                    "evidence_ref": result.get("evidence_ref"),
                }
            )
        deduped, seen = [], set()
        for value in evidence:
            key = canonical_json(value)
            if key not in seen:
                seen.add(key)
                deduped.append(value)
        self.update_root_work_item(
            run_id,
            status=root["status"],
            progress_note=root["progress_note"],
            evidence=deduped[:100],
        )

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def record_attention(
        self, run_id: str, *, kind: str, seconds: int, note: str = ""
    ) -> dict[str, Any]:
        category = str(kind or "").strip().lower()
        if category not in ATTENTION_KINDS:
            raise ValueError("attention kind must be setup/clarification/review/rework/recovery")
        if type(seconds) is not int or not 0 <= seconds <= 86_400:
            raise ValueError("attention seconds must be an integer from 0 to 86400")
        message = str(note or "")
        if len(message.encode("utf-8")) > 4_000:
            raise ValueError("attention note exceeds 4000 UTF-8 bytes")
        attention_id = self._id("attention")
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO delivery_attention(attention_id,run_id,kind,seconds,note) "
                "VALUES(?,?,?,?,?)",
                (attention_id, run_id, category, seconds, message),
            )
        return dict(
            self.store.db.execute(
                "SELECT * FROM delivery_attention WHERE attention_id=?", (attention_id,)
            ).fetchone()
        )

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def run_view(self, run_id: str) -> dict[str, Any]:
        attention = self.store.db.execute(
            "SELECT coalesce(sum(seconds),0) AS seconds,count(*) AS entries "
            "FROM delivery_attention WHERE run_id=?",
            (run_id,),
        ).fetchone()
        return {
            "finalization": self.finalization(run_id),
            "acceptance": self.acceptance(run_id),
            "work_items": self.work_items(run_id),
            "attention": dict(attention),
        }

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def metrics(self) -> dict[str, Any]:
        rows = self.store.db.execute(
            "SELECT state,count(*) AS n FROM delivery_acceptance GROUP BY state"
        ).fetchall()
        counts = {state: 0 for state in ACCEPTANCE_STATES}
        counts.update({row["state"]: int(row["n"]) for row in rows})
        total = sum(counts.values())
        pending = self.store.db.execute(
            "SELECT count(*) FROM delivery_finalizations WHERE state<>'DONE'"
        ).fetchone()[0]
        attention = self.store.db.execute(
            "SELECT coalesce(sum(seconds),0),count(*) FROM delivery_attention"
        ).fetchone()
        failed_completed = self.store.db.execute(
            "SELECT count(*) FROM delivery_acceptance a "
            "JOIN workspace_turns t USING(run_id) "
            "WHERE t.status='COMPLETED' AND a.state='FAILED'"
        ).fetchone()[0]
        return {
            "acceptance": counts,
            "admitted_deliveries": total,
            "acceptance_pass_rate": (counts["PASSED"] / total) if total else None,
            "completed_but_failed_acceptance": int(failed_completed),
            "pending_finalizations": int(pending),
            "human_attention_seconds": int(attention[0] or 0),
            "human_attention_entries": int(attention[1] or 0),
        }

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def reconcile_pending(
        self,
        repository,
        memory,
        personal,
        *,
        run_id: str | None = None,
        limit: int = 32,
    ) -> list[dict[str, Any]]:
        """仅对已 COMPLETED 的回答补派生投影；RUNNING/UNKNOWN 不猜测、不重放。"""
        sql = "SELECT * FROM delivery_finalizations WHERE state<>'DONE'"
        args: list[Any] = []
        if run_id is not None:
            sql += " AND run_id=?"
            args.append(run_id)
        sql += " ORDER BY rowid LIMIT ?"
        args.append(max(1, min(int(limit), 256)))
        reports = []
        for row in self.store.db.execute(sql, tuple(args)).fetchall():
            item = dict(row)
            try:
                turn = repository.turn(item["run_id"])
                if turn["status"] != "COMPLETED":
                    reports.append({"run_id": item["run_id"], "state": item["state"], "action": "wait"})
                    continue
                session = repository.session(turn["session_id"])
                messages = [
                    message for message in session["messages"]
                    if message.get("run_id") == item["run_id"]
                ]
                user = next(
                    (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
                )
                answer = next(
                    (m["content"] for m in reversed(messages) if m.get("role") == "assistant"),
                    item["answer"],
                )
                if not item["memory_done"]:
                    memory.record_episode(item["run_id"], user, answer)
                    with self.store.tx() as db:
                        db.execute(
                            "UPDATE delivery_finalizations SET memory_done=1,attempts=attempts+1,"
                            "last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                            (item["run_id"],),
                        )
                    item["memory_done"] = 1
                if not item["goal_done"]:
                    if item["goal_id"]:
                        personal.checkpoint_run(
                            item["goal_id"],
                            item["run_id"],
                            status="COMPLETED",
                            summary=item["goal_summary"] or answer[:2000],
                            next_action=item["next_action"]
                            or "Review the result and continue the next unfinished part of this goal.",
                            waiting_for=item["waiting_for"],
                        )
                    with self.store.tx() as db:
                        db.execute(
                            "UPDATE delivery_finalizations SET goal_done=1,attempts=attempts+1,"
                            "last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                            (item["run_id"],),
                        )
                    item["goal_done"] = 1
                subject_digest, evidence = self._subject(item["run_id"])
                acceptance = self.ensure_acceptance(item["run_id"], subject_digest, evidence)
                self.update_root_work_item(
                    item["run_id"],
                    status="DONE",
                    progress_note="Conversation answer persisted; semantic acceptance remains explicit.",
                    evidence=evidence,
                )
                with self.store.tx() as db:
                    db.execute(
                        "UPDATE delivery_finalizations SET state='DONE',last_error=NULL,"
                        "updated_at=CURRENT_TIMESTAMP WHERE run_id=? AND memory_done=1 AND goal_done=1",
                        (item["run_id"],),
                    )
                reports.append(
                    {"run_id": item["run_id"], "state": "DONE", "acceptance": acceptance["state"]}
                )
            except Exception as exc:
                with self.store.tx() as db:
                    db.execute(
                        "UPDATE delivery_finalizations SET attempts=attempts+1,last_error=?,"
                        "updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                        (f"{type(exc).__name__}: {exc}"[:2000], item["run_id"]),
                    )
                reports.append(
                    {"run_id": item["run_id"], "state": item["state"], "error": f"{type(exc).__name__}: {exc}"}
                )
        return reports
