"""Exact Agent 的 SQLite 仓储实现。
拥有 Agent 步骤、对话笔记、允许范围与验收投影；持久决定和工具绑定支持恢复，最终交付仍引用独立报告。"""

from __future__ import annotations
import json
import uuid
from typing import Any
from ..decision_runtime import DecisionRuntime
from ..domain import BudgetExceeded, IdentityConflict, canonical_json, digest_json

# SCHEMA：本仓储拥有的当前表、索引与约束；由 Store 原子初始化，不叠加旧格式迁移。
SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
 run_id TEXT PRIMARY KEY REFERENCES runs(run_id), provider_id TEXT NOT NULL,
 model_id TEXT NOT NULL, allowed_files_json TEXT NOT NULL, status TEXT NOT NULL,
 current_step INTEGER NOT NULL DEFAULT 0, max_steps INTEGER NOT NULL,
 max_output_tokens INTEGER NOT NULL, thinking TEXT, pending_question TEXT,
 final_text TEXT, last_decision_id TEXT, error TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS agent_notes (
 run_id TEXT NOT NULL REFERENCES runs(run_id), sequence INTEGER NOT NULL,
 kind TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(run_id,sequence));
CREATE TABLE IF NOT EXISTS agent_verification_reports (
 report_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
 verdict TEXT NOT NULL, claim TEXT NOT NULL, evidence_json TEXT NOT NULL,
 reason TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS agent_deliveries (
 delivery_id TEXT PRIMARY KEY, run_id TEXT UNIQUE NOT NULL REFERENCES runs(run_id),
 report_id TEXT NOT NULL REFERENCES agent_verification_reports(report_id),
 final_text TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS agent_contracts (
 run_id TEXT PRIMARY KEY REFERENCES agent_runs(run_id), manifest_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_settings (
 run_id TEXT PRIMARY KEY REFERENCES agent_runs(run_id), options_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_steps (
 run_id TEXT NOT NULL REFERENCES agent_runs(run_id), step INTEGER NOT NULL,
 state TEXT NOT NULL, decision_id TEXT REFERENCES step_decisions(decision_id),
 decision_json TEXT, PRIMARY KEY(run_id,step));
CREATE TABLE IF NOT EXISTS agent_reads (
 decision_id TEXT PRIMARY KEY REFERENCES step_decisions(decision_id),
 run_id TEXT NOT NULL REFERENCES agent_runs(run_id), ticket_id TEXT UNIQUE NOT NULL,
 payload_json TEXT NOT NULL);
"""


# 拥有 Exact Agent 状态的适配器；共享 Core 执行事实但不拥有外部 I/O。
class SqliteAgentRepository:
    # 复用 Runtime 连接建立 Exact 步骤/笔记/验收表；旧 Run 可检查，缺合同不能推断完成。
    def __init__(self, runtime) -> None:
        # runtime：共享 Runtime 装配对象；其 SQLite 连接只在所属线程使用。
        self.runtime = runtime
        # store：持久事实仓储；短事务维护本地一致性；外部效果不能并入数据库事务。
        self.store = runtime.store
        # decisions：模型请求/收据协调器；提供固定身份，不授予模型直接执行权。
        self.decisions = DecisionRuntime(runtime)
        self.store.ensure_schema(SCHEMA)

    # 生成带类型前缀的新身份；重试去重使用已固定的 request/decision 身份，不靠新 UUID 判断已执行。
    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    # 在当前事务分配并写入 Agent 笔记；笔记顺序随步骤状态一起提交。
    def _note(self, db, run_id, kind, payload):
        seq = db.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM agent_notes WHERE run_id=?",
            (run_id,),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO agent_notes(run_id,sequence,kind,payload_json) VALUES (?,?,?,?)",
            (run_id, seq, kind, canonical_json(payload)),
        )
        self.store._event(
            db, run_id, "AgentNoteRecorded", {"kind": kind, "note_sequence": seq}
        )

    # 同事务创建 Exact 用例、Core Run、预算及固定验收投影；入口冲突不覆盖原 Run。
    def create(self, spec: dict[str, Any], manifest: dict[str, Any]) -> str:
        identity = digest_json(
            {k: v for k, v in spec.items() if k not in {"run_id", "request_id"}}
            | {"manifest": manifest}
        )
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            existing = db.execute(
                "SELECT * FROM runs WHERE request_id=?", (spec["request_id"],)
            ).fetchone()
            if existing:
                if existing["entry_digest"] != identity:
                    raise IdentityConflict(
                        "request_id reused with different goal, baseline, acceptance or limits"
                    )
                return existing["run_id"]
            rid = spec["run_id"]
            # 运行、预算、基线验收、Agent 和初始 note 没有半提交状态。
            db.execute(
                "INSERT INTO runs(run_id,request_id,entry_digest,goal,acceptance_version,state) VALUES (?,?,?,?,?,?)",
                (
                    rid,
                    spec["request_id"],
                    identity,
                    spec["goal"],
                    manifest["digest"],
                    "RUNNING",
                ),
            )
            budgets = {
                "model_calls": spec["max_steps"],
                "input_tokens": 2_000_000,
                "output_tokens": spec["max_steps"] * spec["max_output_tokens"],
                "tool_calls": spec["max_steps"],
                "write_bytes": 16_000_000,
                "read_bytes": 4_000_000,
            }
            for meter, limit in budgets.items():
                db.execute(
                    "INSERT INTO accounts(run_id,meter,limit_units) VALUES (?,?,?)",
                    (rid, meter, limit),
                )
            db.execute(
                "INSERT INTO agent_runs(run_id,provider_id,model_id,allowed_files_json,status,max_steps,max_output_tokens,thinking) VALUES (?,?,?,?,?,?,?,?)",
                (
                    rid,
                    spec["provider_id"],
                    spec["model_id"],
                    canonical_json(spec["allowed_files"]),
                    "RUNNING",
                    spec["max_steps"],
                    spec["max_output_tokens"],
                    spec["thinking"],
                ),
            )
            db.execute(
                "INSERT INTO agent_contracts VALUES (?,?)",
                (rid, canonical_json(manifest)),
            )
            db.execute(
                "INSERT INTO agent_settings VALUES (?,?)",
                (rid, canonical_json(spec.get("provider_options", {}))),
            )
            self.store._event(
                db, rid, "AgentStarted", {"acceptance_digest": manifest["digest"]}
            )
            self._note(db, rid, "goal", {"text": spec["goal"]})
        return rid

    # 读取用例行并校验身份存在；不暴露可修改 SQL 游标给应用。
    def row(self, run_id):
        row = self.store.db.execute(
            "SELECT * FROM agent_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    # 取得该 Run 创建时固定的验收合同；后续决策不能改写目标来制造 PASS。
    def manifest(self, run_id):
        row = self.store.db.execute(
            "SELECT manifest_json FROM agent_contracts WHERE run_id=?", (run_id,)
        ).fetchone()
        # 缺少固定验收合同的旧 Run 仍可检查；不能从模型声明或旧状态推断 PASS。
        return json.loads(row[0]) if row else {"rules": [], "files": []}

    # 按持久顺序读取用例经历；用于上下文恢复而不是权限推断。
    def notes(self, run_id):
        return [
            {
                "sequence": r["sequence"],
                "kind": r["kind"],
                "payload": json.loads(r["payload_json"]),
            }
            for r in self.store.db.execute(
                "SELECT * FROM agent_notes WHERE run_id=? ORDER BY sequence", (run_id,)
            )
        ]

    # 原子分配或复用当前未完成步骤；耗尽步数返回空值，恢复不跳过未消费的决定。
    def begin_step(self, run_id):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            row = self.row(run_id)
            if row["status"] != "RUNNING":
                return None
            unfinished = db.execute(
                "SELECT * FROM agent_steps WHERE run_id=? AND state!='DONE' ORDER BY step LIMIT 1",
                (run_id,),
            ).fetchone()
            if unfinished:
                result = dict(unfinished)
            else:
                if row["current_step"] >= row["max_steps"]:
                    return None
                step = row["current_step"] + 1
                db.execute(
                    "INSERT INTO agent_steps VALUES (?,?,'STARTED',NULL,NULL)",
                    (run_id, step),
                )
                db.execute(
                    "UPDATE agent_runs SET current_step=?,updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                    (step, run_id),
                )
                self.store._event(db, run_id, "AgentStepStarted", {"step": step})
                result = {"step": step, "decision_id": None, "decision_json": None}
            if result["decision_json"]:
                result["decision_json"] = json.loads(result["decision_json"])
            return result

    # 把固定步骤与已记录决定绑定；恢复复用同一身份，不能覆盖成另一个提案。
    def bind_decision(self, run_id, step, decision_id, decision):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "UPDATE agent_steps SET state='DECIDED',decision_id=?,decision_json=? WHERE run_id=? AND step=? AND state='STARTED'",
                (decision_id, canonical_json(decision.serializable()), run_id, step),
            )
            db.execute(
                "UPDATE agent_runs SET last_decision_id=? WHERE run_id=?",
                (decision_id, run_id),
            )
            self._note(
                db,
                run_id,
                "decision",
                {"decision_id": decision_id, **decision.serializable()},
            )

    # 原子记录步骤结果、笔记和下一状态；提交后驱动器再规划下一步。
    def finish_step(self, run_id, step, kind, payload, status="RUNNING"):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            changed = db.execute(
                "UPDATE agent_steps SET state='DONE' WHERE run_id=? AND step=? AND state!='DONE'",
                (run_id, step),
            )
            if not changed.rowcount:
                return
            self._note(db, run_id, kind, payload)
            if self.row(run_id)["status"] == "CANCELLED":
                return  # 迟到事实仍写入；不能覆盖取消状态。
            question = payload.get("text") if status == "WAITING_USER" else None
            db.execute(
                "UPDATE agent_runs SET status=?,pending_question=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                (status, question, run_id),
            )
            db.execute(
                "UPDATE runs SET state=? WHERE run_id=?",
                ("WAITING" if status == "WAITING_USER" else status, run_id),
            )
            self.store._event(
                db, run_id, "AgentStepFinished", {"step": step, "status": status}
            )

    # 持久记录阻塞/结束状态及原因；不抹掉已签发凭证和晚到收据。
    def block(self, run_id, status, reason):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            if self.row(run_id)["status"] in {
                "SUCCEEDED",
                "CANCELLED",
                "FAILED",
                "BUDGET_EXHAUSTED",
            }:
                return
            db.execute(
                "UPDATE agent_runs SET status=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                (status, reason, run_id),
            )
            db.execute(
                "UPDATE runs SET state=? WHERE run_id=?",
                ("RECOVERING" if status == "UNKNOWN" else status, run_id),
            )
            self.store._event(
                db, run_id, "AgentBlocked", {"status": status, "reason": reason}
            )

    # 按当前持久状态重新进入驱动；恢复核对由执行端口负责，不凭重开动作重发未知效果。
    def reopen(self, run_id):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            if self.row(run_id)["status"] not in {"RUNNING", "INTERRUPTED", "UNKNOWN"}:
                return
            db.execute(
                "UPDATE agent_runs SET status='RUNNING',error=NULL WHERE run_id=?",
                (run_id,),
            )
            db.execute("UPDATE runs SET state='RUNNING' WHERE run_id=?", (run_id,))

    # 校验待答问题身份并消费明确用户回答；不同问题不能相互代答。
    def answer(self, run_id, question_id, text):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            row = self.row(run_id)
            if (
                row["status"] != "WAITING_USER"
                or row["last_decision_id"] != question_id
            ):
                raise ValueError("answer must match the current pending question_id")
            if not text.strip():
                raise ValueError("answer must be non-empty")
            self._note(db, run_id, "user", {"text": text, "question_id": question_id})
            db.execute(
                "UPDATE agent_runs SET status='RUNNING',pending_question=NULL WHERE run_id=?",
                (run_id,),
            )
            db.execute("UPDATE runs SET state='RUNNING' WHERE run_id=?", (run_id,))

    # 记录停止未来工作的意图/状态；已发出效果仍按实际结果结算。
    def cancel(self, run_id):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            if self.row(run_id)["status"] in {
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                "BUDGET_EXHAUSTED",
            }:
                return
            db.execute(
                "UPDATE agent_runs SET status='CANCELLED',pending_question=NULL WHERE run_id=?",
                (run_id,),
            )
            db.execute(
                "UPDATE runs SET state='CANCELLED',control_revision=control_revision+1 WHERE run_id=?",
                (run_id,),
            )
            # 没有 Ticket 的意图可证实未启动；与取消一起封闭启动机会并释放预留。
            for reservation in db.execute(
                "SELECT r.* FROM reservations r JOIN attempts a USING(attempt_id) WHERE a.run_id=? AND a.state='INTENT' AND r.closed=0",
                (run_id,),
            ).fetchall():
                db.execute(
                    "UPDATE accounts SET reserved=reserved-? WHERE run_id=? AND meter=?",
                    (reservation["reserved_amount"], run_id, reservation["meter"]),
                )
                db.execute(
                    "UPDATE reservations SET closed=1 WHERE attempt_id=? AND meter=?",
                    (reservation["attempt_id"], reservation["meter"]),
                )
            db.execute(
                "UPDATE attempts SET state='NOT_STARTED',last_error='cancelled before Ticket' WHERE run_id=? AND state='INTENT'",
                (run_id,),
            )
            self.store._event(db, run_id, "AgentCancelled", {})

    def read_receipt(self, run_id, decision_id, payload):
        """以 decision_id 去重保存受管读取结果和计量；已保存读取不重复消耗资源。"""
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            existing = db.execute(
                "SELECT payload_json FROM agent_reads WHERE decision_id=? AND run_id=?",
                (decision_id, run_id),
            ).fetchone()
            if existing:
                return json.loads(existing[0])
            if self.row(run_id)["status"] != "RUNNING":
                raise ValueError("run does not admit reads")
            owner = db.execute(
                "SELECT run_id FROM step_decisions WHERE decision_id=?", (decision_id,)
            ).fetchone()
            if owner is None or owner[0] != run_id:
                raise ValueError("read decision must belong to this run")
            for meter, amount in {
                "tool_calls": 1,
                "read_bytes": payload["read_bytes"],
            }.items():
                changed = db.execute(
                    "UPDATE accounts SET settled=settled+? WHERE run_id=? AND meter=? AND limit_units-settled-reserved-unknown_held>=?",
                    (amount, run_id, meter, amount),
                )
                if not changed.rowcount:
                    raise BudgetExceeded(f"insufficient {meter} budget")
            payload = {**payload, "ticket_id": self._id("read_tkt")}
            db.execute(
                "INSERT INTO agent_reads VALUES (?,?,?,?)",
                (decision_id, run_id, payload["ticket_id"], canonical_json(payload)),
            )
            self.store._event(
                db,
                run_id,
                "ManagedReadRecorded",
                {"decision_id": decision_id, "snapshot_ref": payload["snapshot_ref"]},
            )
            return payload

    # 只有固定验收通过才提交候选、报告与交付投影；completion claim 本身不够。
    def verify_and_deliver(self, run_id, step, verdict, reason, decision, candidate):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            if self.row(run_id)["status"] != "RUNNING":
                return
            manifest = self.manifest(run_id)
            report_id = self._id("avr")
            evidence = {
                "cited": list(decision.evidence_refs),
                "acceptance_digest": manifest.get("digest"),
                "candidate": candidate,
            }
            if verdict == "PASS" and (
                not manifest.get("rules")
                or any(
                    candidate.get(f["path"]) != f["expected_digest"]
                    for f in manifest["files"]
                )
            ):
                raise ValueError("PASS must bind the fixed complete candidate")
            db.execute(
                "INSERT INTO agent_verification_reports(report_id,run_id,verdict,claim,evidence_json,reason) VALUES (?,?,?,?,?,?)",
                (
                    report_id,
                    run_id,
                    verdict,
                    decision.claim or "",
                    canonical_json(evidence),
                    reason,
                ),
            )
            db.execute(
                "UPDATE agent_steps SET state='DONE' WHERE run_id=? AND step=?",
                (run_id, step),
            )
            self.store._event(
                db,
                run_id,
                "AgentVerificationRecorded",
                {"report_id": report_id, "verdict": verdict, "reason": reason},
            )
            if verdict != "PASS":
                self._note(
                    db,
                    run_id,
                    "verification_rejected",
                    {"report_id": report_id, "reason": reason},
                )
                return
            delivery_id = self._id("adel")
            db.execute(
                "INSERT INTO agent_deliveries(delivery_id,run_id,report_id,final_text) VALUES (?,?,?,?)",
                (delivery_id, run_id, report_id, decision.claim or "Completed"),
            )
            db.execute(
                "UPDATE agent_runs SET status='SUCCEEDED',final_text=?,pending_question=NULL WHERE run_id=?",
                (decision.claim, run_id),
            )
            db.execute("UPDATE runs SET state='SUCCEEDED' WHERE run_id=?", (run_id,))
            self._note(
                db,
                run_id,
                "final",
                {"text": decision.claim, "delivery_id": delivery_id},
            )
            self.store._event(
                db,
                run_id,
                "AgentDelivered",
                {"delivery_id": delivery_id, "report_id": report_id},
            )

    # 读取有界 Run 列表供产品/CLI 展示；这是历史投影，不重新驱动任何 Run。
    def list_runs(self, limit=50):
        return [
            dict(r)
            for r in self.store.db.execute(
                "SELECT a.*,r.goal,r.state AS run_state FROM agent_runs a JOIN runs r USING(run_id) ORDER BY a.created_at DESC,a.rowid DESC LIMIT ?",
                (limit,),
            )
        ]

    # 读取当前持久事实并生成状态投影；不得把模型 claim 当作已执行或已验收。
    def status(self, run_id):
        agent = self.row(run_id)
        agent["allowed_files"] = json.loads(agent["allowed_files_json"])
        agent["question_id"] = (
            agent["last_decision_id"] if agent["status"] == "WAITING_USER" else None
        )
        options = self.store.db.execute(
            "SELECT options_json FROM agent_settings WHERE run_id=?", (run_id,)
        ).fetchone()
        agent["provider_options"] = json.loads(options[0]) if options else {}
        reports = [
            {**dict(r), "evidence": json.loads(r["evidence_json"])}
            for r in self.store.db.execute(
                "SELECT * FROM agent_verification_reports WHERE run_id=? ORDER BY rowid",
                (run_id,),
            )
        ]
        delivery = self.store.db.execute(
            "SELECT * FROM agent_deliveries WHERE run_id=?", (run_id,)
        ).fetchone()
        actions = [
            dict(r)
            for r in self.store.db.execute(
                "SELECT a.*,p.state AS attempt_state,p.outcome,p.attempt_id,r.evidence_ref FROM actions a JOIN attempts p USING(action_id) LEFT JOIN receipts r USING(attempt_id) WHERE a.run_id=? ORDER BY a.rowid",
                (run_id,),
            )
        ]
        return {
            "run": self.store.get_run(run_id),
            "agent": agent,
            "notes": self.notes(run_id),
            "acceptance": self.manifest(run_id),
            "model": self.decisions.status(run_id),
            "tool_actions": actions,
            "verification": reports,
            "delivery": dict(delivery) if delivery else None,
        }
