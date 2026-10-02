"""SQLite 适配器：Agent 状态、步骤消费、固定验收和交付的唯一写入者。

公开接口是事务级用例。状态、步骤、事件与必要 note 一起提交；模型和
文件 I/O 在事务外。复用已有账本，不创建第二套执行预算。
"""
from __future__ import annotations
import json
import uuid
from typing import Any
from ..decision_runtime import DecisionRuntime
from ..domain import BudgetExceeded, IdentityConflict, canonical_json, digest_json

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


class SqliteAgentRepository:
    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.store = runtime.store
        self.decisions = DecisionRuntime(runtime)
        self.store.db.executescript(SCHEMA)

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def _note(self, db, run_id, kind, payload):
        seq = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM agent_notes WHERE run_id=?", (run_id,)).fetchone()[0]
        db.execute("INSERT INTO agent_notes(run_id,sequence,kind,payload_json) VALUES (?,?,?,?)",
                   (run_id, seq, kind, canonical_json(payload)))
        self.store._event(db, run_id, "AgentNoteRecorded", {"kind": kind, "note_sequence": seq})

    def create(self, spec: dict[str, Any], manifest: dict[str, Any]) -> str:
        identity = digest_json({k: v for k, v in spec.items() if k not in {"run_id", "request_id"}} | {"manifest": manifest})
        with self.store.tx() as db:
            existing = db.execute("SELECT * FROM runs WHERE request_id=?", (spec["request_id"],)).fetchone()
            if existing:
                if existing["entry_digest"] != identity:
                    raise IdentityConflict("request_id reused with different goal, baseline, acceptance or limits")
                return existing["run_id"]
            rid = spec["run_id"]
            # 运行、预算、基线验收、Agent 和初始 note 没有半提交状态。
            db.execute("INSERT INTO runs(run_id,request_id,entry_digest,goal,acceptance_version,state) VALUES (?,?,?,?,?,?)",
                       (rid, spec["request_id"], identity, spec["goal"], manifest["digest"], "RUNNING"))
            budgets = {"model_calls": spec["max_steps"], "input_tokens": 2_000_000,
                       "output_tokens": spec["max_steps"] * spec["max_output_tokens"],
                       "tool_calls": spec["max_steps"], "write_bytes": 16_000_000, "read_bytes": 4_000_000}
            for meter, limit in budgets.items():
                db.execute("INSERT INTO accounts(run_id,meter,limit_units) VALUES (?,?,?)", (rid, meter, limit))
            db.execute("INSERT INTO agent_runs(run_id,provider_id,model_id,allowed_files_json,status,max_steps,max_output_tokens,thinking) VALUES (?,?,?,?,?,?,?,?)",
                       (rid, spec["provider_id"], spec["model_id"], canonical_json(spec["allowed_files"]), "RUNNING",
                        spec["max_steps"], spec["max_output_tokens"], spec["thinking"]))
            db.execute("INSERT INTO agent_contracts VALUES (?,?)", (rid, canonical_json(manifest)))
            db.execute("INSERT INTO agent_settings VALUES (?,?)", (rid, canonical_json(spec.get("provider_options", {}))))
            self.store._event(db, rid, "AgentStarted", {"acceptance_digest": manifest["digest"]})
            self._note(db, rid, "goal", {"text": spec["goal"]})
        return rid

    def row(self, run_id):
        row = self.store.db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    def manifest(self, run_id):
        row = self.store.db.execute("SELECT manifest_json FROM agent_contracts WHERE run_id=?", (run_id,)).fetchone()
        # Legacy P3 runs lack a goal contract: keep them inspectable, never infer a PASS.
        return json.loads(row[0]) if row else {"rules": [], "files": []}

    def notes(self, run_id):
        return [{"sequence": r["sequence"], "kind": r["kind"], "payload": json.loads(r["payload_json"])}
                for r in self.store.db.execute("SELECT * FROM agent_notes WHERE run_id=? ORDER BY sequence", (run_id,))]

    def begin_step(self, run_id):
        with self.store.tx() as db:
            row = self.row(run_id)
            if row["status"] != "RUNNING":
                return None
            unfinished = db.execute("SELECT * FROM agent_steps WHERE run_id=? AND state!='DONE' ORDER BY step LIMIT 1", (run_id,)).fetchone()
            if unfinished:
                result = dict(unfinished)
            else:
                if row["current_step"] >= row["max_steps"]:
                    return None
                step = row["current_step"] + 1
                db.execute("INSERT INTO agent_steps VALUES (?,?,'STARTED',NULL,NULL)", (run_id, step))
                db.execute("UPDATE agent_runs SET current_step=?,updated_at=CURRENT_TIMESTAMP WHERE run_id=?", (step, run_id))
                self.store._event(db, run_id, "AgentStepStarted", {"step": step})
                result = {"step": step, "decision_id": None, "decision_json": None}
            if result["decision_json"]:
                result["decision_json"] = json.loads(result["decision_json"])
            return result

    def bind_decision(self, run_id, step, decision_id, decision):
        with self.store.tx() as db:
            db.execute("UPDATE agent_steps SET state='DECIDED',decision_id=?,decision_json=? WHERE run_id=? AND step=? AND state='STARTED'",
                       (decision_id, canonical_json(decision.serializable()), run_id, step))
            db.execute("UPDATE agent_runs SET last_decision_id=? WHERE run_id=?", (decision_id, run_id))
            self._note(db, run_id, "decision", {"decision_id": decision_id, **decision.serializable()})

    def finish_step(self, run_id, step, kind, payload, status="RUNNING"):
        with self.store.tx() as db:
            changed = db.execute("UPDATE agent_steps SET state='DONE' WHERE run_id=? AND step=? AND state!='DONE'", (run_id, step))
            if not changed.rowcount:
                return
            self._note(db, run_id, kind, payload)
            if self.row(run_id)["status"] == "CANCELLED":
                return  # 迟到事实仍写入；不能覆盖取消状态。
            question = payload.get("text") if status == "WAITING_USER" else None
            db.execute("UPDATE agent_runs SET status=?,pending_question=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                       (status, question, run_id))
            db.execute("UPDATE runs SET state=? WHERE run_id=?", ("WAITING" if status == "WAITING_USER" else status, run_id))
            self.store._event(db, run_id, "AgentStepFinished", {"step": step, "status": status})

    def block(self, run_id, status, reason):
        with self.store.tx() as db:
            if self.row(run_id)["status"] in {"SUCCEEDED", "CANCELLED", "FAILED", "BUDGET_EXHAUSTED"}:
                return
            db.execute("UPDATE agent_runs SET status=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE run_id=?", (status, reason, run_id))
            db.execute("UPDATE runs SET state=? WHERE run_id=?", ("RECOVERING" if status == "UNKNOWN" else status, run_id))
            self.store._event(db, run_id, "AgentBlocked", {"status": status, "reason": reason})

    def reopen(self, run_id):
        with self.store.tx() as db:
            if self.row(run_id)["status"] not in {"RUNNING", "UNKNOWN"}:
                return
            db.execute("UPDATE agent_runs SET status='RUNNING',error=NULL WHERE run_id=?", (run_id,))
            db.execute("UPDATE runs SET state='RUNNING' WHERE run_id=?", (run_id,))

    def answer(self, run_id, question_id, text):
        with self.store.tx() as db:
            row = self.row(run_id)
            if row["status"] != "WAITING_USER" or row["last_decision_id"] != question_id:
                raise ValueError("answer must match the current pending question_id")
            if not text.strip():
                raise ValueError("answer must be non-empty")
            self._note(db, run_id, "user", {"text": text, "question_id": question_id})
            db.execute("UPDATE agent_runs SET status='RUNNING',pending_question=NULL WHERE run_id=?", (run_id,))
            db.execute("UPDATE runs SET state='RUNNING' WHERE run_id=?", (run_id,))

    def cancel(self, run_id):
        with self.store.tx() as db:
            if self.row(run_id)["status"] in {"SUCCEEDED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"}:
                return
            db.execute("UPDATE agent_runs SET status='CANCELLED',pending_question=NULL WHERE run_id=?", (run_id,))
            db.execute("UPDATE runs SET state='CANCELLED',control_revision=control_revision+1 WHERE run_id=?", (run_id,))
            # 没有 Ticket 的意图可证实未启动；与取消一起封闭启动机会并释放预留。
            for reservation in db.execute("SELECT r.* FROM reservations r JOIN attempts a USING(attempt_id) WHERE a.run_id=? AND a.state='INTENT' AND r.closed=0", (run_id,)).fetchall():
                db.execute("UPDATE accounts SET reserved=reserved-? WHERE run_id=? AND meter=?",
                           (reservation["reserved_amount"], run_id, reservation["meter"]))
                db.execute("UPDATE reservations SET closed=1 WHERE attempt_id=? AND meter=?", (reservation["attempt_id"], reservation["meter"]))
            db.execute("UPDATE attempts SET state='NOT_STARTED',last_error='cancelled before Ticket' WHERE run_id=? AND state='INTENT'", (run_id,))
            self.store._event(db, run_id, "AgentCancelled", {})

    def read_receipt(self, run_id, decision_id, payload):
        """受管读取是不可变对象的内部投影；准入、计量、快照收据同事务提交。"""
        with self.store.tx() as db:
            existing = db.execute("SELECT payload_json FROM agent_reads WHERE decision_id=? AND run_id=?", (decision_id, run_id)).fetchone()
            if existing:
                return json.loads(existing[0])
            if self.row(run_id)["status"] != "RUNNING":
                raise ValueError("run does not admit reads")
            owner = db.execute("SELECT run_id FROM step_decisions WHERE decision_id=?", (decision_id,)).fetchone()
            if owner is None or owner[0] != run_id:
                raise ValueError("read decision must belong to this run")
            for meter, amount in {"tool_calls": 1, "read_bytes": payload["read_bytes"]}.items():
                changed = db.execute("UPDATE accounts SET settled=settled+? WHERE run_id=? AND meter=? AND limit_units-settled-reserved-unknown_held>=?",
                                     (amount, run_id, meter, amount))
                if not changed.rowcount:
                    raise BudgetExceeded(f"insufficient {meter} budget")
            payload = {**payload, "ticket_id": self._id("read_tkt")}
            db.execute("INSERT INTO agent_reads VALUES (?,?,?,?)", (decision_id, run_id, payload["ticket_id"], canonical_json(payload)))
            self.store._event(db, run_id, "ManagedReadRecorded", {"decision_id": decision_id, "snapshot_ref": payload["snapshot_ref"]})
            return payload

    def verify_and_deliver(self, run_id, step, verdict, reason, decision, candidate):
        with self.store.tx() as db:
            if self.row(run_id)["status"] != "RUNNING":
                return
            manifest = self.manifest(run_id)
            report_id = self._id("avr")
            evidence = {"cited": list(decision.evidence_refs), "acceptance_digest": manifest.get("digest"), "candidate": candidate}
            if verdict == "PASS" and (not manifest.get("rules") or any(candidate.get(f["path"]) != f["expected_digest"] for f in manifest["files"])):
                raise ValueError("PASS must bind the fixed complete candidate")
            db.execute("INSERT INTO agent_verification_reports(report_id,run_id,verdict,claim,evidence_json,reason) VALUES (?,?,?,?,?,?)",
                       (report_id, run_id, verdict, decision.claim or "", canonical_json(evidence), reason))
            db.execute("UPDATE agent_steps SET state='DONE' WHERE run_id=? AND step=?", (run_id, step))
            self.store._event(db, run_id, "AgentVerificationRecorded", {"report_id": report_id, "verdict": verdict, "reason": reason})
            if verdict != "PASS":
                self._note(db, run_id, "verification_rejected", {"report_id": report_id, "reason": reason})
                return
            delivery_id = self._id("adel")
            db.execute("INSERT INTO agent_deliveries(delivery_id,run_id,report_id,final_text) VALUES (?,?,?,?)",
                       (delivery_id, run_id, report_id, decision.claim or "Completed"))
            db.execute("UPDATE agent_runs SET status='SUCCEEDED',final_text=?,pending_question=NULL WHERE run_id=?", (decision.claim, run_id))
            db.execute("UPDATE runs SET state='SUCCEEDED' WHERE run_id=?", (run_id,))
            self._note(db, run_id, "final", {"text": decision.claim, "delivery_id": delivery_id})
            self.store._event(db, run_id, "AgentDelivered", {"delivery_id": delivery_id, "report_id": report_id})

    def list_runs(self, limit=50):
        return [dict(r) for r in self.store.db.execute("SELECT a.*,r.goal,r.state AS run_state FROM agent_runs a JOIN runs r USING(run_id) ORDER BY a.created_at DESC,a.rowid DESC LIMIT ?", (limit,))]

    def status(self, run_id):
        agent = self.row(run_id)
        agent["allowed_files"] = json.loads(agent["allowed_files_json"])
        agent["question_id"] = agent["last_decision_id"] if agent["status"] == "WAITING_USER" else None
        options = self.store.db.execute("SELECT options_json FROM agent_settings WHERE run_id=?", (run_id,)).fetchone()
        agent["provider_options"] = json.loads(options[0]) if options else {}
        reports = [{**dict(r), "evidence": json.loads(r["evidence_json"])} for r in self.store.db.execute("SELECT * FROM agent_verification_reports WHERE run_id=? ORDER BY rowid", (run_id,))]
        delivery = self.store.db.execute("SELECT * FROM agent_deliveries WHERE run_id=?", (run_id,)).fetchone()
        actions = [dict(r) for r in self.store.db.execute("SELECT a.*,p.state AS attempt_state,p.outcome,p.attempt_id,r.evidence_ref FROM actions a JOIN attempts p USING(action_id) LEFT JOIN receipts r USING(attempt_id) WHERE a.run_id=? ORDER BY a.rowid", (run_id,))]
        return {"run": self.store.get_run(run_id), "agent": agent, "notes": self.notes(run_id),
                "acceptance": self.manifest(run_id), "model": self.decisions.status(run_id),
                "tool_actions": actions, "verification": reports, "delivery": dict(delivery) if delivery else None}
