"""P3 Agent loop: durable decisions -> durable tools -> independent completion.

The loop is deliberately small. It can execute the existing exact-patch tool,
ask the user for missing information, and finish only after an independent
verifier binds the model's completion claim to durable tool evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
import uuid
from typing import Any

from .decision_runtime import DecisionRuntime
from .domain import (
    BudgetExceeded,
    PatchContractError,
    RecoveryRequired,
    RunState,
    Verdict,
    canonical_json,
    sha256_bytes,
)
from .models import StepDecision
from .providers.base import ModelProvider
from .runtime import MythRuntime


AGENT_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY NOT NULL REFERENCES runs(run_id),
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    allowed_files_json TEXT NOT NULL,
    status TEXT NOT NULL,
    current_step INTEGER NOT NULL DEFAULT 0,
    max_steps INTEGER NOT NULL,
    max_output_tokens INTEGER NOT NULL,
    thinking TEXT,
    pending_question TEXT,
    final_text TEXT,
    last_decision_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_notes (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    sequence INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(run_id, sequence)
);

CREATE TABLE IF NOT EXISTS agent_verification_reports (
    report_id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    verdict TEXT NOT NULL,
    claim TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_deliveries (
    delivery_id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
    report_id TEXT NOT NULL REFERENCES agent_verification_reports(report_id),
    final_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class AgentRuntime:
    """A bounded single-agent loop over the durable P1/P2 primitives."""

    def __init__(self, runtime: MythRuntime) -> None:
        self.runtime = runtime
        self.store = runtime.store
        self.decisions = DecisionRuntime(runtime)
        self.store.db.executescript(AGENT_SCHEMA)

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def _event(self, db, run_id: str, kind: str, payload: dict[str, Any]) -> None:
        row = db.execute("SELECT next_sequence FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        seq = int(row[0])
        db.execute("UPDATE runs SET next_sequence=next_sequence+1 WHERE run_id=?", (run_id,))
        db.execute(
            "INSERT INTO events(run_id,sequence,kind,payload_json) VALUES (?,?,?,?)",
            (run_id, seq, kind, canonical_json(payload)),
        )

    def _note(self, run_id: str, kind: str, payload: dict[str, Any]) -> None:
        with self.store.tx() as db:
            row = db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM agent_notes WHERE run_id=?",
                (run_id,),
            ).fetchone()
            sequence = int(row[0])
            db.execute(
                "INSERT INTO agent_notes(run_id,sequence,kind,payload_json) VALUES (?,?,?,?)",
                (run_id, sequence, kind, canonical_json(payload)),
            )

    def _set_agent(
        self,
        run_id: str,
        *,
        status: str | None = None,
        current_step: int | None = None,
        pending_question: str | None = None,
        clear_question: bool = False,
        final_text: str | None = None,
        last_decision_id: str | None = None,
        error: str | None = None,
    ) -> None:
        assignments = ["updated_at=CURRENT_TIMESTAMP"]
        values: list[Any] = []
        for column, value in (
            ("status", status),
            ("current_step", current_step),
            ("final_text", final_text),
            ("last_decision_id", last_decision_id),
            ("error", error),
        ):
            if value is not None:
                assignments.append(f"{column}=?")
                values.append(value)
        if clear_question:
            assignments.append("pending_question=NULL")
        elif pending_question is not None:
            assignments.append("pending_question=?")
            values.append(pending_question)
        values.append(run_id)
        with self.store.tx() as db:
            db.execute(
                f"UPDATE agent_runs SET {','.join(assignments)} WHERE run_id=?",
                values,
            )

    def _set_run_state(self, run_id: str, state: RunState, event: str, payload: dict[str, Any]) -> None:
        with self.store.tx() as db:
            db.execute("UPDATE runs SET state=? WHERE run_id=?", (state.value, run_id))
            self._event(db, run_id, event, payload)

    def create_run(
        self,
        *,
        goal: str,
        provider: ModelProvider,
        model: str,
        allowed_files: tuple[Path, ...],
        max_steps: int = 6,
        max_output_tokens: int = 1024,
        thinking: str | None = None,
        request_id: str | None = None,
    ) -> str:
        if type(max_steps) is not int or max_steps < 2:
            raise ValueError("max_steps must be at least 2")
        files = tuple(path.resolve() for path in allowed_files)
        for path in files:
            if not path.is_file():
                raise FileNotFoundError(path)
        run_id = self.decisions.create_goal_run(
            goal=goal,
            provider_id=provider.provider_id,
            model_id=model,
            allowed_files=files,
            max_output_tokens=max_output_tokens,
            max_model_calls=max_steps,
            max_tool_calls=max_steps - 1,
            request_id=request_id,
        )
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO agent_runs(run_id,provider_id,model_id,allowed_files_json,status,max_steps,"
                "max_output_tokens,thinking) VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    provider.provider_id,
                    model,
                    canonical_json([str(path) for path in files]),
                    "RUNNING",
                    max_steps,
                    max_output_tokens,
                    thinking,
                ),
            )
            self._event(
                db,
                run_id,
                "AgentStarted",
                {"provider": provider.provider_id, "model": model, "max_steps": max_steps},
            )
        self._note(run_id, "goal", {"text": goal})
        return run_id

    def _agent_row(self, run_id: str) -> dict[str, Any]:
        row = self.store.db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    def _allowed_files(self, run_id: str) -> tuple[Path, ...]:
        row = self._agent_row(run_id)
        return tuple(Path(item) for item in json.loads(row["allowed_files_json"]))

    def _context(self, run_id: str) -> str:
        notes = []
        for row in self.store.db.execute(
            "SELECT sequence,kind,payload_json FROM agent_notes WHERE run_id=? ORDER BY sequence",
            (run_id,),
        ).fetchall():
            notes.append(
                {
                    "sequence": int(row["sequence"]),
                    "kind": row["kind"],
                    "payload": json.loads(row["payload_json"]),
                }
            )
        return canonical_json({"history": notes[-24:]})

    def _resolve_allowed_file(self, run_id: str, value: Any) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("tool path must be a non-empty string")
        allowed = self._allowed_files(run_id)
        raw = Path(value)
        candidates = []
        if raw.is_absolute():
            candidates.append(raw.resolve())
        else:
            candidates.append((self.runtime.root / raw).resolve())
            candidates.extend(path for path in allowed if path.name == raw.name)
        for candidate in candidates:
            if candidate in allowed:
                return candidate
        raise PermissionError("model proposed a path outside the explicit allowed_files set")

    def _execute_tool(self, run_id: str, decision: StepDecision) -> dict[str, Any]:
        if decision.capability_id != "file.patch_exact":
            raise PermissionError(f"capability is not admitted: {decision.capability_id}")
        args = decision.arguments or {}
        source = self._resolve_allowed_file(run_id, args.get("path"))
        old_text = args.get("old_text")
        new_text = args.get("new_text")
        expected_count = args.get("expected_count")
        if not isinstance(old_text, str) or not old_text:
            raise ValueError("old_text must be a non-empty string")
        if not isinstance(new_text, str):
            raise ValueError("new_text must be a string")
        if type(expected_count) is not int or expected_count <= 0:
            raise ValueError("expected_count must be a positive integer")

        prepared = self.runtime.prepare_patch_action(
            run_id,
            source,
            old_text=old_text,
            new_text=new_text,
            expected_count=expected_count,
        )
        result = self.runtime.execute_patch_action(run_id)
        receipt = result.get("receipt") or {}
        evidence_ref = str(receipt.get("evidence_ref") or "")
        managed = Path(result["managed_file"])
        text_preview = managed.read_text(encoding="utf-8", errors="replace")
        payload = {
            "capability_id": decision.capability_id,
            "action_id": prepared["action_id"],
            "attempt_id": prepared["attempt_id"],
            "source_file": str(source),
            "managed_file": str(managed),
            "after_digest": prepared["after_digest"],
            "evidence_ref": evidence_ref,
            "preview": text_preview[:12_000],
        }
        self._note(run_id, "tool_result", payload)
        return payload

    def _known_tool_evidence(self, run_id: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        rows = self.store.db.execute(
            "SELECT a.*,p.state AS attempt_state,p.outcome,p.attempt_id,r.evidence_ref "
            "FROM actions a "
            "JOIN attempts p ON p.action_id=a.action_id "
            "LEFT JOIN receipts r ON r.attempt_id=p.attempt_id "
            "WHERE a.run_id=? ORDER BY a.rowid",
            (run_id,),
        ).fetchall()
        for row in rows:
            item = dict(row)
            evidence_ref = item.get("evidence_ref")
            if evidence_ref:
                result[str(evidence_ref)] = item
        return result

    def _verify_completion(self, run_id: str, decision: StepDecision) -> tuple[str, Verdict, str]:
        evidence = self._known_tool_evidence(run_id)
        cited = list(decision.evidence_refs)
        verdict = Verdict.PASS
        reason = "completion claim is bound to durable tool evidence and current managed digests"

        if not cited:
            verdict = Verdict.INCONCLUSIVE
            reason = "completion claim did not cite any durable tool evidence"
        elif any(ref not in evidence for ref in cited):
            verdict = Verdict.INCONCLUSIVE
            reason = "completion claim cites unknown evidence"
        else:
            for ref in cited:
                item = evidence[ref]
                if item["attempt_state"] != "RESOLVED" or item["outcome"] != "SUCCEEDED":
                    verdict = Verdict.INCONCLUSIVE
                    reason = "cited tool attempt is not durably successful"
                    break
                path = self.runtime.workspaces.path_for(run_id, item["target_name"])
                if not path.exists() or sha256_bytes(path.read_bytes()) != item["after_digest"]:
                    verdict = Verdict.INCONCLUSIVE
                    reason = "current managed artifact no longer matches cited tool result"
                    break

        report_id = self._id("avr")
        report_evidence = {
            "cited": cited,
            "known": sorted(evidence),
        }
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO agent_verification_reports(report_id,run_id,verdict,claim,evidence_json,reason) "
                "VALUES (?,?,?,?,?,?)",
                (
                    report_id,
                    run_id,
                    verdict.value,
                    decision.claim or "",
                    canonical_json(report_evidence),
                    reason,
                ),
            )
            self._event(
                db,
                run_id,
                "AgentVerificationRecorded",
                {"report_id": report_id, "verdict": verdict.value, "reason": reason},
            )
        return report_id, verdict, reason

    def _deliver(self, run_id: str, report_id: str, decision: StepDecision) -> dict[str, Any]:
        final_text = decision.claim or "Completed."
        delivery_id = self._id("adel")
        with self.store.tx() as db:
            report = db.execute(
                "SELECT * FROM agent_verification_reports WHERE report_id=?",
                (report_id,),
            ).fetchone()
            if report is None or report["verdict"] != Verdict.PASS.value:
                raise RuntimeError("agent delivery requires PASS verification")
            existing = db.execute(
                "SELECT * FROM agent_deliveries WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if existing is None:
                db.execute(
                    "INSERT INTO agent_deliveries(delivery_id,run_id,report_id,final_text) VALUES (?,?,?,?)",
                    (delivery_id, run_id, report_id, final_text),
                )
            else:
                delivery_id = str(existing["delivery_id"])
            db.execute("UPDATE runs SET state=? WHERE run_id=?", (RunState.SUCCEEDED.value, run_id))
            db.execute(
                "UPDATE agent_runs SET status='SUCCEEDED',final_text=?,pending_question=NULL,"
                "updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                (final_text, run_id),
            )
            self._event(
                db,
                run_id,
                "AgentDelivered",
                {"delivery_id": delivery_id, "report_id": report_id},
            )
        self._note(run_id, "final", {"text": final_text, "delivery_id": delivery_id})
        return {"delivery_id": delivery_id, "report_id": report_id, "final_text": final_text}

    def run(self, run_id: str, provider: ModelProvider) -> dict[str, Any]:
        """Advance until success, user input, uncertainty, or the step budget."""

        row = self._agent_row(run_id)
        if row["status"] in {"SUCCEEDED", "FAILED", "BUDGET_EXHAUSTED", "UNKNOWN"}:
            return self.status(run_id)
        if row["status"] == "WAITING_USER":
            return self.status(run_id)

        max_steps = int(row["max_steps"])
        for step in range(int(row["current_step"]) + 1, max_steps + 1):
            self._set_agent(run_id, status="RUNNING", current_step=step, clear_question=True, error="")
            try:
                decision_id, decision = self.decisions.request_decision(
                    run_id=run_id,
                    provider=provider,
                    model=row["model_id"],
                    allowed_files=self._allowed_files(run_id),
                    context=self._context(run_id),
                    max_output_tokens=int(row["max_output_tokens"]),
                    thinking=row["thinking"],
                )
            except Exception as exc:
                self._set_agent(run_id, status="UNKNOWN", error=f"{type(exc).__name__}: {exc}")
                self._set_run_state(
                    run_id,
                    RunState.RECOVERING,
                    "AgentBlockedByUnknownModelOutcome",
                    {"error": f"{type(exc).__name__}: {exc}"},
                )
                return self.status(run_id)

            self._set_agent(run_id, last_decision_id=decision_id)
            self._note(
                run_id,
                "decision",
                {"decision_id": decision_id, **decision.serializable()},
            )

            if decision.decision_type == "ask_user":
                question = decision.question or "More information is required."
                self._set_agent(run_id, status="WAITING_USER", pending_question=question)
                self._note(run_id, "question", {"text": question})
                return self.status(run_id)

            if decision.decision_type == "tool_call":
                try:
                    self._execute_tool(run_id, decision)
                except (PatchContractError, ValueError, PermissionError) as exc:
                    self._note(
                        run_id,
                        "tool_rejected",
                        {"error": f"{type(exc).__name__}: {exc}"},
                    )
                    continue
                except (BudgetExceeded, RecoveryRequired) as exc:
                    self._set_agent(run_id, status="UNKNOWN", error=f"{type(exc).__name__}: {exc}")
                    self._set_run_state(
                        run_id,
                        RunState.RECOVERING,
                        "AgentBlockedByUnknownToolOutcome",
                        {"error": f"{type(exc).__name__}: {exc}"},
                    )
                    return self.status(run_id)
                continue

            report_id, verdict, reason = self._verify_completion(run_id, decision)
            if verdict is Verdict.PASS:
                self._deliver(run_id, report_id, decision)
                return self.status(run_id)
            self._note(
                run_id,
                "verification_rejected",
                {"report_id": report_id, "reason": reason},
            )

        self._set_agent(
            run_id,
            status="BUDGET_EXHAUSTED",
            error="agent reached max_steps without verified completion",
        )
        self._set_run_state(
            run_id,
            RunState.BUDGET_EXHAUSTED,
            "AgentStepBudgetExhausted",
            {"max_steps": max_steps},
        )
        return self.status(run_id)

    def resume(self, run_id: str, provider: ModelProvider, user_text: str) -> dict[str, Any]:
        row = self._agent_row(run_id)
        if row["status"] != "WAITING_USER":
            raise RuntimeError("agent is not waiting for user input")
        if not user_text.strip():
            raise ValueError("user_text must be non-empty")
        self._note(run_id, "user", {"text": user_text.strip()})
        self._set_agent(run_id, status="RUNNING", clear_question=True)
        return self.run(run_id, provider)

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.store.db.execute(
            "SELECT a.*,r.goal,r.state AS run_state,r.created_at AS run_created_at "
            "FROM agent_runs a JOIN runs r ON r.run_id=a.run_id "
            "ORDER BY r.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def status(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        agent = self._agent_row(run_id)
        notes = []
        for row in self.store.db.execute(
            "SELECT * FROM agent_notes WHERE run_id=? ORDER BY sequence",
            (run_id,),
        ).fetchall():
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            notes.append(item)
        verification = [
            {**dict(row), "evidence": json.loads(row["evidence_json"])}
            for row in self.store.db.execute(
                "SELECT * FROM agent_verification_reports WHERE run_id=? ORDER BY created_at",
                (run_id,),
            ).fetchall()
        ]
        for item in verification:
            item.pop("evidence_json", None)
        delivery = self.store.db.execute(
            "SELECT * FROM agent_deliveries WHERE run_id=?",
            (run_id,),
        ).fetchone()
        return {
            "run": run,
            "agent": {
                **agent,
                "allowed_files": json.loads(agent["allowed_files_json"]),
            },
            "notes": notes,
            "model": self.decisions.status(run_id),
            "tool_actions": [
                dict(row)
                for row in self.store.db.execute(
                    "SELECT a.*,p.state AS attempt_state,p.outcome,p.attempt_id,r.evidence_ref,r.usage_json "
                    "FROM actions a JOIN attempts p ON p.action_id=a.action_id "
                    "LEFT JOIN receipts r ON r.attempt_id=p.attempt_id "
                    "WHERE a.run_id=? ORDER BY a.rowid",
                    (run_id,),
                ).fetchall()
            ],
            "verification": verification,
            "delivery": None if delivery is None else dict(delivery),
        }
