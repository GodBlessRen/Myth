"""模型调用的持久准入、派发、收据和决策绑定协调器。
固定 request_key 与请求对象，再预留预算并签发 Ticket；供应商 I/O 在事务外，已发出但结果不明的调用先核对而非重发。"""

from __future__ import annotations

import json
from pathlib import Path
import uuid
from typing import Any

from .artifacts import atomic_write
from .acceptance import ContextBudgetError
from .domain import (
    AttemptState,
    BudgetExceeded,
    InvalidTransition,
    RecoveryRequired,
    canonical_json,
    digest_json,
)
from .models import (
    ContextTruncated,
    DecisionValidationError,
    ModelMessage,
    ModelRequest,
    ModelResult,
    STEP_DECISION_SCHEMA,
    StepDecision,
    parse_step_decision,
)
from .providers.base import ModelProvider
from .runtime import MythRuntime


# MODEL_SCHEMA：模型调用、决定与笔记的 SQLite 表定义；请求对象和收据文件在数据库外按身份核对。
MODEL_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS model_invocations (
    model_attempt_id TEXT PRIMARY KEY NOT NULL,
    model_action_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    request_ref TEXT NOT NULL,
    state TEXT NOT NULL,
    ticket_id TEXT UNIQUE,
    response_ref TEXT,
    response_id TEXT,
    outcome TEXT,
    usage_json TEXT NOT NULL DEFAULT '{}',
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS model_reservations (
    model_attempt_id TEXT NOT NULL REFERENCES model_invocations(model_attempt_id),
    run_id TEXT NOT NULL,
    meter TEXT NOT NULL,
    reserved_amount INTEGER NOT NULL CHECK(reserved_amount >= 0),
    closed INTEGER NOT NULL DEFAULT 0 CHECK(closed IN (0,1)),
    PRIMARY KEY(model_attempt_id, meter),
    FOREIGN KEY(run_id, meter) REFERENCES accounts(run_id, meter)
);

CREATE TABLE IF NOT EXISTS step_decisions (
    decision_id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    model_attempt_id TEXT NOT NULL UNIQUE REFERENCES model_invocations(model_attempt_id),
    decision_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    response_ref TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS model_request_keys (
    request_key TEXT PRIMARY KEY NOT NULL,
    model_attempt_id TEXT UNIQUE NOT NULL REFERENCES model_invocations(model_attempt_id)
);
"""


class DecisionRuntime:
    """模型调用协调器；同 request_key 绑定同请求，收据先发布再结算，恢复不再次调用不明供应商请求。"""

    # 复用 Runtime 连接和不可变对象库建立模型事实表；目录内收据与数据库分开提交，恢复按固定请求身份核对。
    def __init__(self, runtime: MythRuntime) -> None:
        # runtime：共享 Runtime 装配对象；其 SQLite 连接只在所属线程使用。
        self.runtime = runtime
        # store：持久事实仓储；短事务维护本地一致性；外部效果不能并入数据库事务。
        self.store = runtime.store
        # objects：按摘要寻址的不可变字节库；复用时仍核对内容。
        self.objects = runtime.objects
        # receipt_dir：本适配器的收据目录；恢复读取稳定机会身份对应的文件。
        self.receipt_dir = runtime.runtime_dir / "model-receipts"
        self.receipt_dir.mkdir(parents=True, exist_ok=True)
        self.store.db.executescript(MODEL_SCHEMA)

    # 生成带类型前缀的新身份；重试去重使用已固定的 request/decision 身份，不靠新 UUID 判断已执行。
    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    # 在已有 Core 写事务中记有序模型事件；不得单独提交打破状态/事件一致性。
    def _event(self, db, run_id: str, kind: str, payload: dict[str, Any]) -> None:
        row = db.execute(
            "SELECT next_sequence FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        seq = int(row[0])
        db.execute(
            "UPDATE runs SET next_sequence=next_sequence+1 WHERE run_id=?", (run_id,)
        )
        db.execute(
            "INSERT INTO events(run_id,sequence,kind,payload_json) VALUES (?,?,?,?)",
            (run_id, seq, kind, canonical_json(payload)),
        )

    def create_goal_run(
        self,
        *,
        goal: str,
        provider_id: str,
        model_id: str,
        allowed_files: tuple[Path, ...] = (),
        max_output_tokens: int = 1024,
        max_model_calls: int = 3,
        max_tool_calls: int = 0,
        write_bytes_limit: int | None = None,
        request_id: str | None = None,
    ) -> str:
        """创建模型驱动 Core Run 及模型/工具预算；稳定入口身份防止不同内容复用。"""

        if not goal.strip():
            raise ValueError("goal must be non-empty")
        if type(max_model_calls) is not int or max_model_calls <= 0:
            raise ValueError("max_model_calls must be a positive integer")
        if type(max_tool_calls) is not int or max_tool_calls < 0:
            raise ValueError("max_tool_calls must be a non-negative integer")
        allowed = [str(path.resolve()) for path in allowed_files]
        entry = {
            "kind": "agent_goal",
            "goal": goal,
            "provider": provider_id,
            "model": model_id,
            "allowed_files": allowed,
            "decision_schema": "step-decision-v1",
        }
        run_id = self._id("run")
        budgets = {
            "model_calls": max_model_calls,
            "input_tokens": 2_000_000,
            "output_tokens": max_output_tokens * max_model_calls,
        }
        if max_tool_calls:
            total_source_bytes = sum(
                path.stat().st_size
                for path in allowed_files
                if path.exists() and path.is_file()
            )
            budgets["tool_calls"] = max_tool_calls
            budgets["write_bytes"] = (
                write_bytes_limit
                if write_bytes_limit is not None
                else max(1_000_000, total_source_bytes * max_tool_calls * 2)
            )
        run_id, _ = self.store.create_run(
            run_id=run_id,
            request_id=request_id or self._id("req"),
            entry_digest=digest_json(entry),
            goal=goal,
            acceptance_version="agent-goal-v1",
            budgets=budgets,
        )
        return run_id

    # 从统一模型/允许范围构造固定请求合同；只生成投影，尚未调用供应商。
    def _build_request(
        self,
        run_id: str,
        model: str,
        allowed_files: tuple[Path, ...],
        context: str,
        max_output_tokens: int,
        thinking: str | None,
    ) -> ModelRequest:
        run = self.store.get_run(run_id)
        system = (
            "You propose exactly one next step. Myth Runtime owns permissions, budgets, execution and verification. "
            "Return only the requested JSON object. For unused fields return empty strings/lists. "
            "A tool proposal is not proof that the tool ran. "
            "For request_completion, copy the exact evidence_ref strings from successful tool_result history into evidence_refs."
        )
        user = canonical_json(
            {
                "goal": run["goal"],
                "context": context,
                "allowed_files": [str(path.resolve()) for path in allowed_files],
                "tool_catalog": {
                    "file.read": {
                        "arguments": ["path", "offset", "limit"],
                        "rule": "read the fixed managed file; offset/limit are Unicode character units; limit <= 3000",
                    },
                    "file.patch_exact": {
                        "arguments": ["path", "old_text", "new_text", "expected_count"],
                        "rule": "path must be one of allowed_files; arguments_json must encode a JSON object",
                    },
                },
                "decision_rules": [
                    "tool_call only proposes work",
                    "ask_user when required information is missing",
                    "request_completion only when supplied evidence already proves the goal",
                    "request_completion must cite exact tool_result evidence_ref values in evidence_refs",
                ],
            }
        )
        return ModelRequest(
            model=model,
            messages=(ModelMessage("system", system), ModelMessage("user", user)),
            response_schema=STEP_DECISION_SCHEMA,
            max_output_tokens=max_output_tokens,
            thinking=thinking,
        )

    # 同事务登记模型机会、全部预算预留和唯一开始凭证；供应商调用在提交之后。
    def _reserve_and_ticket(
        self,
        *,
        run_id: str,
        provider_id: str,
        model_id: str,
        request_ref: str,
        request_digest: str,
        input_hold: int,
        output_hold: int,
        request_key: str | None = None,
        context_report: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        action_id = self._id("mact")
        attempt_id = self._id("matt")
        ticket_id = self._id("mtkt")
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            run = db.execute(
                "SELECT state FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None or run["state"] != "RUNNING":
                raise InvalidTransition("Run is not accepting model work")
            db.execute(
                "INSERT INTO model_invocations(model_attempt_id,model_action_id,run_id,provider_id,model_id,"
                "request_digest,request_ref,state) VALUES (?,?,?,?,?,?,?,?)",
                (
                    attempt_id,
                    action_id,
                    run_id,
                    provider_id,
                    model_id,
                    request_digest,
                    request_ref,
                    AttemptState.INTENT.value,
                ),
            )
            for meter, amount in {
                "model_calls": 1,
                "input_tokens": input_hold,
                "output_tokens": output_hold,
            }.items():
                changed = db.execute(
                    "UPDATE accounts SET reserved=reserved+? WHERE run_id=? AND meter=? "
                    "AND limit_units-settled-reserved-unknown_held>=?",
                    (amount, run_id, meter, amount),
                )
                if changed.rowcount != 1:
                    raise BudgetExceeded(
                        f"insufficient or missing model budget meter: {meter}"
                    )
                db.execute(
                    "INSERT INTO model_reservations(model_attempt_id,run_id,meter,reserved_amount) VALUES (?,?,?,?)",
                    (attempt_id, run_id, meter, amount),
                )
            self._event(
                db,
                run_id,
                "ModelIntentRecorded",
                {"model_attempt_id": attempt_id, "provider": provider_id},
            )
            db.execute(
                "UPDATE model_invocations SET state=?,ticket_id=? WHERE model_attempt_id=?",
                (AttemptState.TICKETED.value, ticket_id, attempt_id),
            )
            if request_key is not None:
                db.execute(
                    "INSERT INTO model_request_keys VALUES (?,?)",
                    (request_key, attempt_id),
                )
            self._event(
                db,
                run_id,
                "ModelTicketGranted",
                {"model_attempt_id": attempt_id, "ticket_id": ticket_id},
            )
            if context_report is not None:
                self._event(
                    db,
                    run_id,
                    "ConversationContextCompiled",
                    {
                        **context_report,
                        "model_attempt_id": attempt_id,
                        "request_ref": request_ref,
                    },
                )
        return attempt_id, ticket_id

    # 定位每个 model_attempt 的固定收据文件；相同机会不能换路径伪造新调用。
    def _receipt_path(self, attempt_id: str) -> Path:
        return self.receipt_dir / f"{attempt_id}.json"

    # 先发布模型结果与请求绑定的不可变收据对象，再交给数据库结算。
    def _publish_receipt(
        self,
        *,
        attempt_id: str,
        request_digest: str,
        response_ref: str,
        result: ModelResult,
    ) -> dict[str, Any]:
        receipt = {
            "model_attempt_id": attempt_id,
            "request_digest": request_digest,
            "response_ref": response_ref,
            "response_id": result.response_id,
            "text": result.text,
            "usage": result.usage,
        }
        encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
        path = self._receipt_path(attempt_id)
        if path.exists() and path.read_bytes() != encoded:
            raise IOError("conflicting model receipt for the same Attempt")
        if not path.exists():
            atomic_write(path, encoded)
        return receipt

    # 发布供应商明确失败的脱敏证据和已测用量；已知拒绝与无响应不混为一谈。
    def _publish_failure_receipt(
        self,
        *,
        attempt_id: str,
        request_digest: str,
        response_ref: str,
        reason: str,
        usage: dict[str, int],
    ) -> dict[str, Any]:
        receipt = {
            "model_attempt_id": attempt_id,
            "request_digest": request_digest,
            "response_ref": response_ref,
            "response_id": None,
            "outcome": "FAILED",
            "reason": reason,
            "usage": usage,
        }
        encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
        path = self._receipt_path(attempt_id)
        if path.exists() and path.read_bytes() != encoded:
            raise IOError("conflicting model failure receipt for the same Attempt")
        if not path.exists():
            atomic_write(path, encoded)
        return receipt

    # 据已知失败收据原子结算模型机会与预算；不重发同一请求来掩盖失败。
    def _settle_failed(self, attempt_id: str, receipt: dict[str, Any]) -> None:
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            row = db.execute(
                "SELECT * FROM model_invocations WHERE model_attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise KeyError(attempt_id)
            if row["request_digest"] != receipt["request_digest"]:
                raise RuntimeError(
                    "model failure receipt does not match the frozen request"
                )
            usage = (
                receipt.get("usage") if isinstance(receipt.get("usage"), dict) else {}
            )
            for reservation in db.execute(
                "SELECT * FROM model_reservations WHERE model_attempt_id=?",
                (attempt_id,),
            ).fetchall():
                meter = str(reservation["meter"])
                reserved = int(reservation["reserved_amount"])
                if meter in usage:
                    actual = int(usage[meter])
                    if actual < 0:
                        raise ValueError("model usage cannot be negative")
                    db.execute(
                        "UPDATE accounts SET reserved=reserved-?,settled=settled+? WHERE run_id=? AND meter=?",
                        (reserved, actual, reservation["run_id"], meter),
                    )
                else:
                    db.execute(
                        "UPDATE accounts SET reserved=reserved-?,unknown_held=unknown_held+? WHERE run_id=? AND meter=?",
                        (reserved, reserved, reservation["run_id"], meter),
                    )
                db.execute(
                    "UPDATE model_reservations SET closed=1 WHERE model_attempt_id=? AND meter=?",
                    (attempt_id, meter),
                )
            db.execute(
                "UPDATE model_invocations SET state=?,outcome='FAILED',response_ref=?,usage_json=?,last_error=? "
                "WHERE model_attempt_id=?",
                (
                    AttemptState.RESOLVED.value,
                    receipt["response_ref"],
                    canonical_json(usage),
                    receipt["reason"],
                    attempt_id,
                ),
            )
            self._event(
                db,
                row["run_id"],
                "ModelAttemptFailed",
                {"model_attempt_id": attempt_id, "reason": receipt["reason"]},
            )

    # 据固定收据原子记入模型结果与用量；未报告的计量仍保留 unknown-held。
    def _settle(self, attempt_id: str, receipt: dict[str, Any]) -> None:
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            row = db.execute(
                "SELECT * FROM model_invocations WHERE model_attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise KeyError(attempt_id)
            if row["state"] == AttemptState.RESOLVED.value:
                if row["response_ref"] != receipt["response_ref"]:
                    raise RuntimeError(
                        "model Attempt already resolved by another response"
                    )
                return
            if row["request_digest"] != receipt["request_digest"]:
                raise RuntimeError("model receipt does not match the frozen request")
            usage = (
                receipt.get("usage") if isinstance(receipt.get("usage"), dict) else {}
            )
            for reservation in db.execute(
                "SELECT * FROM model_reservations WHERE model_attempt_id=?",
                (attempt_id,),
            ).fetchall():
                meter = str(reservation["meter"])
                reserved = int(reservation["reserved_amount"])
                actual = int(usage.get(meter, 0))
                if actual < 0:
                    raise ValueError("model usage cannot be negative")
                # 迟到收据从 UNKNOWN 占用结算，不能再次扣减已转移的预留。
                held_column = "unknown_held" if reservation["closed"] else "reserved"
                if meter in usage:
                    db.execute(
                        f"UPDATE accounts SET {held_column}={held_column}-?,settled=settled+? WHERE run_id=? AND meter=?",
                        (reserved, actual, reservation["run_id"], meter),
                    )
                elif not reservation["closed"]:
                    db.execute(
                        "UPDATE accounts SET reserved=reserved-?,unknown_held=unknown_held+? WHERE run_id=? AND meter=?",
                        (reserved, reserved, reservation["run_id"], meter),
                    )
                db.execute(
                    "UPDATE model_reservations SET closed=1 WHERE model_attempt_id=? AND meter=?",
                    (attempt_id, meter),
                )
            db.execute(
                "UPDATE model_invocations SET state=?,outcome='SUCCEEDED',response_ref=?,response_id=?,usage_json=?,last_error=NULL "
                "WHERE model_attempt_id=?",
                (
                    AttemptState.RESOLVED.value,
                    receipt["response_ref"],
                    receipt.get("response_id"),
                    canonical_json(usage),
                    attempt_id,
                ),
            )
            self._event(
                db,
                row["run_id"],
                "ModelAttemptSettled",
                {"model_attempt_id": attempt_id},
            )

    # 记录已派发模型结果不明的机会，保留预算和身份供人工/后续核对。
    def _mark_unknown(self, attempt_id: str, reason: str) -> None:
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            row = db.execute(
                "SELECT * FROM model_invocations WHERE model_attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None or row["state"] == AttemptState.RESOLVED.value:
                return
            for reservation in db.execute(
                "SELECT * FROM model_reservations WHERE model_attempt_id=? AND closed=0",
                (attempt_id,),
            ).fetchall():
                amount = int(reservation["reserved_amount"])
                db.execute(
                    "UPDATE accounts SET reserved=reserved-?,unknown_held=unknown_held+? WHERE run_id=? AND meter=?",
                    (amount, amount, reservation["run_id"], reservation["meter"]),
                )
                db.execute(
                    "UPDATE model_reservations SET closed=1 WHERE model_attempt_id=? AND meter=?",
                    (attempt_id, reservation["meter"]),
                )
            db.execute(
                "UPDATE model_invocations SET state=?,outcome='UNKNOWN',last_error=? WHERE model_attempt_id=?",
                (AttemptState.UNKNOWN.value, reason, attempt_id),
            )
            self._event(
                db,
                row["run_id"],
                "ModelAttemptUnknown",
                {"model_attempt_id": attempt_id, "reason": reason},
            )

    # 把结构校验后的模型提案固定成 StepDecision；该记录不是工具收据或执行授权。
    def _save_decision(
        self, run_id: str, attempt_id: str, response_ref: str, decision: StepDecision
    ) -> str:
        payload = canonical_json(decision.serializable())
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            existing = db.execute(
                "SELECT decision_id,payload_json FROM step_decisions WHERE model_attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if existing is not None:
                if existing["payload_json"] != payload:
                    raise RuntimeError(
                        "model Attempt already produced a different StepDecision"
                    )
                return str(existing["decision_id"])
            decision_id = self._id("dec")
            db.execute(
                "INSERT INTO step_decisions(decision_id,run_id,model_attempt_id,decision_type,payload_json,response_ref) "
                "VALUES (?,?,?,?,?,?)",
                (
                    decision_id,
                    run_id,
                    attempt_id,
                    decision.decision_type,
                    payload,
                    response_ref,
                ),
            )
            self._event(
                db,
                run_id,
                "StepDecisionCommitted",
                {"decision_id": decision_id, "decision_type": decision.decision_type},
            )
        return decision_id

    def request_decision(
        self,
        *,
        run_id: str,
        provider: ModelProvider,
        model: str,
        allowed_files: tuple[Path, ...] = (),
        context: str = "",
        max_output_tokens: int = 1024,
        thinking: str | None = None,
        request_key: str | None = None,
        model_request_override: ModelRequest | None = None,
    ) -> tuple[str, StepDecision]:
        """按 request_key 去重，准备/准入后在事务外调用供应商；再发布收据、结算、校验并绑定决定。"""

        if request_key is not None:
            existing = self.store.db.execute(
                "SELECT m.* FROM model_request_keys k JOIN model_invocations m USING(model_attempt_id) WHERE request_key=?",
                (request_key,),
            ).fetchone()
            if existing is not None:
                if existing["run_id"] != run_id:
                    raise ValueError("model request key belongs to another run")
                self.recover(run_id)
                saved = self.store.db.execute(
                    "SELECT * FROM step_decisions WHERE model_attempt_id=?",
                    (existing["model_attempt_id"],),
                ).fetchone()
                if saved is not None:
                    return saved["decision_id"], StepDecision(
                        **json.loads(saved["payload_json"])
                    )
                receipt_path = self._receipt_path(existing["model_attempt_id"])
                if receipt_path.exists():
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                    decision = parse_step_decision(receipt["text"])
                    return (
                        self._save_decision(
                            run_id,
                            existing["model_attempt_id"],
                            receipt["response_ref"],
                            decision,
                        ),
                        decision,
                    )
                raise RecoveryRequired(
                    "this step already owns a model Ticket without a durable response"
                )
        model_request = model_request_override or self._build_request(
            run_id, model, allowed_files, context, max_output_tokens, thinking
        )
        request_bytes = json.dumps(
            model_request.serializable(), ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        if len(request_bytes) > 65_536:
            raise ContextBudgetError(
                "serialized model request exceeds the 65536-byte preflight limit"
            )
        request_ref = self.objects.put(request_bytes)
        request_digest = digest_json(model_request.serializable())
        attempt_id, _ = self._reserve_and_ticket(
            run_id=run_id,
            provider_id=provider.provider_id,
            model_id=model,
            request_ref=request_ref,
            request_digest=request_digest,
            input_hold=len(request_bytes),
            output_hold=max_output_tokens,
            request_key=request_key,
            context_report=model_request.context_report,
        )
        try:
            result = provider.invoke(model_request)
        except ContextTruncated as exc:
            response_ref = self.objects.put(
                json.dumps(exc.raw, ensure_ascii=False, sort_keys=True).encode("utf-8")
            )
            receipt = self._publish_failure_receipt(
                attempt_id=attempt_id,
                request_digest=request_digest,
                response_ref=response_ref,
                reason=str(exc),
                usage=exc.usage,
            )
            self._settle_failed(attempt_id, receipt)
            raise ContextBudgetError(str(exc)) from exc
        except Exception as exc:
            self._mark_unknown(
                attempt_id,
                f"provider call raised after Ticket: {type(exc).__name__}: {exc}",
            )
            raise

        response_ref = self.objects.put(
            json.dumps(result.raw, ensure_ascii=False, sort_keys=True).encode("utf-8")
        )
        receipt = self._publish_receipt(
            attempt_id=attempt_id,
            request_digest=request_digest,
            response_ref=response_ref,
            result=result,
        )
        self._settle(attempt_id, receipt)
        decision = parse_step_decision(result.text)
        decision_id = self._save_decision(run_id, attempt_id, response_ref, decision)
        return decision_id, decision

    def recover(self, run_id: str | None = None) -> list[dict[str, Any]]:
        """用已有请求、Ticket、收据和对象核对执行状态；没有足够事实时保留 UNKNOWN，不盲目重发。"""

        sql = "SELECT * FROM model_invocations WHERE state IN (?,?)"
        args: list[Any] = [AttemptState.TICKETED.value, AttemptState.UNKNOWN.value]
        if run_id is not None:
            sql += " AND run_id=?"
            args.append(run_id)
        recovered: list[dict[str, Any]] = []
        for row in self.store.db.execute(sql, args).fetchall():
            attempt_id = str(row["model_attempt_id"])
            path = self._receipt_path(attempt_id)
            if not path.exists():
                self._mark_unknown(
                    attempt_id,
                    "model Ticket exists but no durable response receipt is available",
                )
                recovered.append({"model_attempt_id": attempt_id, "state": "UNKNOWN"})
                continue
            receipt = json.loads(path.read_text(encoding="utf-8"))
            self._settle(attempt_id, receipt)
            try:
                decision = parse_step_decision(str(receipt["text"]))
                decision_id = self._save_decision(
                    str(row["run_id"]),
                    attempt_id,
                    str(receipt["response_ref"]),
                    decision,
                )
                recovered.append(
                    {
                        "model_attempt_id": attempt_id,
                        "state": "RESOLVED",
                        "decision_id": decision_id,
                    }
                )
            except DecisionValidationError as exc:
                recovered.append(
                    {
                        "model_attempt_id": attempt_id,
                        "state": "RESOLVED",
                        "decision_error": str(exc),
                    }
                )
        return recovered

    # 读取当前持久事实并生成状态投影；不得把模型 claim 当作已执行或已验收。
    def status(self, run_id: str) -> dict[str, Any]:
        invocations = []
        for row in self.store.db.execute(
            "SELECT * FROM model_invocations WHERE run_id=? ORDER BY rowid", (run_id,)
        ).fetchall():
            item = dict(row)
            try:
                item["usage"] = json.loads(item.get("usage_json") or "{}")
            except json.JSONDecodeError:
                item["usage"] = {}
            invocations.append(item)
        decisions = []
        for row in self.store.db.execute(
            "SELECT * FROM step_decisions WHERE run_id=? ORDER BY created_at", (run_id,)
        ).fetchall():
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            decisions.append(item)
        return {
            "run": self.store.get_run(run_id),
            "model_invocations": invocations,
            "decisions": decisions,
            "budgets": self.store.get_accounts(run_id),
            "events": self.store.get_events(run_id),
        }
