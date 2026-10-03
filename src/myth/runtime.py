"""受管精确文件任务的装配与执行协调入口。
连接 RuntimeStore、对象库、受管副本、收据与独立验收；文件效果在事务外，通过摘要和日志核对，不改写用户原文件。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import uuid
from typing import Any

from .artifacts import ManagedWorkspace, ObjectStore, ReceiptJournal, atomic_write
from .domain import (
    AttemptState,
    Outcome,
    ReceiptData,
    RecoveryRequired,
    RunState,
    SimulatedCrash,
    Verdict,
    digest_json,
    exact_patch,
    sha256_bytes,
)
from .store import RuntimeStore


class MythRuntime:
    """本机 I/O 的装配根和精确任务协调器；每次使用关闭自己的连接，共享事实经 SQLite 与对象目录持久化。"""

    # ACCEPTANCE_VERSION：精确字节验收合同版本；摘要/报告绑定此版本而非当前模型选择。
    ACCEPTANCE_VERSION = "exact-file-v1"

    # 在明确根目录装配数据库、摘要对象、受管副本和收据日志；只创建本机资源，不自动派发模型或工具。
    def __init__(self, root: str | Path) -> None:
        # root：已明确选择的根目录；具体读写仍由对应受限适配器校验。
        self.root = Path(root).resolve()
        # runtime_dir：当前 Runtime 的隔离状态目录；包含数据库、不可变对象、收据和受管副本。
        self.runtime_dir = self.root / ".runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        # store：持久事实仓储；短事务维护本地一致性；外部效果不能并入数据库事务。
        self.store = RuntimeStore(self.runtime_dir / "runtime.db")
        # objects：按摘要寻址的不可变字节库；复用时仍核对内容。
        self.objects = ObjectStore(self.runtime_dir / "objects")
        # workspaces：每 Run 的受管文件副本；不直接覆盖用户原始文件。
        self.workspaces = ManagedWorkspace(self.runtime_dir / "workspaces")
        # journal：按 Attempt 身份保存的效果收据日志；先发布后数据库结算。
        self.journal = ReceiptJournal(self.runtime_dir / "receipts")
        (self.runtime_dir / "deliveries").mkdir(parents=True, exist_ok=True)

    # 关闭本实例持有的连接/资源；持久 Run 和收据生命周期继续保留。
    def close(self) -> None:
        self.store.close()

    # 进入本机资源作用域并返回可用对象；与退出路径配对管理资源生命周期。
    def __enter__(self) -> "MythRuntime":
        return self

    # 离开作用域释放本实例资源；异常继续传播，不能在清理时伪造业务成功。
    def __exit__(self, *_: object) -> None:
        self.close()

    # 生成带类型前缀的新身份；重试去重使用已固定的 request/decision 身份，不靠新 UUID 判断已执行。
    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def submit_patch(
        self,
        source_path: str | Path,
        *,
        old_text: str,
        new_text: str,
        expected_count: int,
        request_id: str | None = None,
        budgets: dict[str, int] | None = None,
    ) -> str:
        """先准备固定对象及私有基线，再原子准入 Run/预算/Action/Attempt。

        文件与数据库不共享事务；准备失败不会留下 Run，数据库失败最多留下未引用的
        私有基线/对象，不能当作已授权效果。真实替换仍须后续 StartTicket。
        """

        source = Path(source_path)
        data = source.read_bytes()
        plan = exact_patch(data, old_text, new_text, expected_count)
        self.objects.put(plan.before)
        self.objects.put(plan.after)

        target_name = source.name
        entry = {
            "kind": "file.patch_exact",
            "target_name": target_name,
            "before_digest": plan.before_digest,
            "after_digest": plan.after_digest,
            "old_text": old_text,
            "new_text": new_text,
            "expected_count": expected_count,
            "acceptance_version": self.ACCEPTANCE_VERSION,
        }
        entry_digest = digest_json(entry)
        request_id = request_id or self._id("req")
        existing = self.store.request_run(request_id, entry_digest)
        if existing is not None:
            return existing
        run_id = self._id("run")

        default_budgets = {
            "tool_calls": 2,
            "write_bytes": max(len(plan.after) * 2, 1),
        }
        # 仅准备私有副本，不修改原文件；在数据库事务外完成，避免长写锁或伪跨系统原子性。
        self.workspaces.materialize(run_id, target_name, plan.before)

        action_id = self._id("act")
        attempt_id = self._id("att")
        request_digest = digest_json({"entry": entry, "run_id": run_id})
        envelope_digest = digest_json(
            {
                "run_id": run_id,
                "action_id": action_id,
                "attempt_id": attempt_id,
                "request_digest": request_digest,
                "acceptance_version": self.ACCEPTANCE_VERSION,
            }
        )
        action = {
            "action_id": action_id,
            "run_id": run_id,
            "kind": "file.patch_exact",
            "request_digest": request_digest,
            "target_name": target_name,
            "before_digest": plan.before_digest,
            "after_digest": plan.after_digest,
            "old_text": old_text,
            "new_text": new_text,
            "expected_count": expected_count,
        }
        attempt = {
            "attempt_id": attempt_id,
            "attempt_no": 1,
            "envelope_digest": envelope_digest,
        }
        # 一个业务决定：Run、预算、初始 Intent 及首批事件不可部分提交。
        with self.store.tx() as db:
            admitted_id, created = self.store.create_run(
                run_id=run_id,
                request_id=request_id,
                entry_digest=entry_digest,
                goal=f"Replace {old_text!r} with {new_text!r} exactly {expected_count} time(s) in {target_name}",
                acceptance_version=self.ACCEPTANCE_VERSION,
                budgets=budgets or default_budgets,
                _db=db,
            )
            if not created:
                # 另一连接已提交同入口；复用其完整 Run，当前私有准备不获得 Ticket。
                return admitted_id
            self.store.create_action_attempt(
                action=action,
                attempt=attempt,
                reservations={"tool_calls": 1, "write_bytes": len(plan.after)},
                _db=db,
            )
        return run_id

    def prepare_patch_action(
        self,
        run_id: str,
        source_path: str | Path,
        *,
        old_text: str,
        new_text: str,
        expected_count: int,
        decision_id: str | None = None,
    ) -> dict[str, Any]:
        """在已准入 Run 内以固定 decision_id 绑定精确修改；已有受管副本作为下一基线，用户原文件不原地修改。"""

        source = Path(source_path).resolve()
        target_name = source.name
        managed = self.workspaces.path_for(run_id, target_name)
        if decision_id is not None:
            bound = self.store.db.execute(
                "SELECT action_id FROM agent_tool_bindings WHERE decision_id=?",
                (decision_id,),
            ).fetchone()
            if bound is not None:
                action = self.store.get_action(bound[0])
                if action["run_id"] != run_id:
                    raise ValueError("bound tool action belongs to another run")
                attempt = self.store.get_attempt_for_action(action["action_id"])
                return {
                    **action,
                    "attempt_id": attempt["attempt_id"],
                    "managed_file": str(managed),
                }
        before = managed.read_bytes() if managed.exists() else source.read_bytes()
        plan = exact_patch(before, old_text, new_text, expected_count)
        self.objects.put(plan.before)
        self.objects.put(plan.after)
        if not managed.exists():
            self.workspaces.materialize(run_id, target_name, plan.before)

        action_id = self._id("act")
        attempt_id = self._id("att")
        request = {
            "kind": "file.patch_exact",
            "run_id": run_id,
            "source": str(source),
            "target_name": target_name,
            "before_digest": plan.before_digest,
            "after_digest": plan.after_digest,
            "old_text": old_text,
            "new_text": new_text,
            "expected_count": expected_count,
        }
        request_digest = digest_json(request)
        envelope_digest = digest_json(
            {
                "run_id": run_id,
                "action_id": action_id,
                "attempt_id": attempt_id,
                "request_digest": request_digest,
                "acceptance_version": self.store.get_run(run_id)["acceptance_version"],
            }
        )
        self.store.create_action_attempt(
            action={
                "action_id": action_id,
                "run_id": run_id,
                "kind": "file.patch_exact",
                "request_digest": request_digest,
                "target_name": target_name,
                "before_digest": plan.before_digest,
                "after_digest": plan.after_digest,
                "old_text": old_text,
                "new_text": new_text,
                "expected_count": expected_count,
            },
            attempt={
                "attempt_id": attempt_id,
                "attempt_no": 1,
                "envelope_digest": envelope_digest,
            },
            reservations={"tool_calls": 1, "write_bytes": len(plan.after)},
            decision_id=decision_id,
        )
        return {
            "action_id": action_id,
            "attempt_id": attempt_id,
            "target_name": target_name,
            "before_digest": plan.before_digest,
            "after_digest": plan.after_digest,
            "managed_file": str(managed),
        }

    def execute_patch_action(
        self, run_id: str, *, action_id: str | None = None
    ) -> dict[str, Any]:
        """只派发 INTENT 并结算收据；TICKETED/UNKNOWN 先核对，RESOLVED 复用事实，不完成整个 Goal。"""

        action = (
            self.store.get_action(action_id)
            if action_id
            else self.store.get_action_for_run(run_id)
        )
        if action["run_id"] != run_id:
            raise ValueError("action belongs to another run")
        attempt = self.store.get_attempt_for_action(action["action_id"])
        if attempt["state"] == AttemptState.INTENT.value:
            ticket = self.store.start_attempt(attempt["attempt_id"], self._id("tkt"))
            attempt = self.store.get_attempt_for_action(action["action_id"])
        elif attempt["state"] == AttemptState.TICKETED.value:
            raise RecoveryRequired(
                "Attempt already has a Ticket; reconcile before dispatching it again"
            )
        elif attempt["state"] == AttemptState.RESOLVED.value:
            receipt = self.store.db.execute(
                "SELECT * FROM receipts WHERE attempt_id=? ORDER BY rowid DESC LIMIT 1",
                (attempt["attempt_id"],),
            ).fetchone()
            return {
                "action": action,
                "attempt": attempt,
                "managed_file": str(
                    self.workspaces.path_for(run_id, action["target_name"])
                ),
                "receipt": dict(receipt) if receipt else {},
            }
        else:
            raise RecoveryRequired(
                f"Attempt is {attempt['state']}; reconcile before continuing"
            )

        receipt = self._execute_ticket(run_id, attempt, ticket, None)
        self.store.settle_receipt(receipt, usage_known=True)
        return {
            "action": action,
            "attempt": self.store.get_attempt_for_action(action["action_id"]),
            "receipt": {
                "receipt_id": receipt.receipt_id,
                "outcome": receipt.outcome.value,
                "evidence_ref": receipt.evidence_ref,
                "usage": receipt.usage,
            },
            "managed_file": str(
                self.workspaces.path_for(run_id, action["target_name"])
            ),
        }

    # 根据固定前后摘要核对受管文件并发布收据；效果前后故障注入验证日志恢复，不把文件替换当作 DB 事务。
    def _execute_ticket(
        self,
        run_id: str,
        attempt: dict[str, Any],
        ticket: dict[str, Any],
        failpoint: str | None,
    ) -> ReceiptData:
        action = self.store.get_action(attempt["action_id"])
        path = self.workspaces.path_for(run_id, action["target_name"])
        current = path.read_bytes()
        current_digest = sha256_bytes(current)

        if ticket["envelope_digest"] != attempt["envelope_digest"]:
            raise RecoveryRequired(
                "Ticket no longer matches the frozen Attempt envelope"
            )

        after = self.objects.get(action["after_digest"])
        wrote = False
        if current_digest == action["before_digest"]:
            atomic_write(path, after)
            wrote = True
        elif current_digest == action["after_digest"]:
            wrote = False
        else:
            raise RecoveryRequired(
                "managed file is neither the fixed before nor expected after version"
            )

        if failpoint == "hard_after_write_before_receipt":
            os._exit(91)
        if failpoint == "after_write_before_receipt":
            raise SimulatedCrash("crash after file effect, before receipt journal")

        receipt = ReceiptData(
            receipt_id=self._id("rcpt"),
            attempt_id=attempt["attempt_id"],
            envelope_digest=attempt["envelope_digest"],
            outcome=Outcome.SUCCEEDED,
            evidence_ref=f"workspace:{run_id}/{action['target_name']}@{action['after_digest']}",
            usage={"tool_calls": 1, "write_bytes": len(after) if wrote else 0},
        )
        # 先发布稳定机会的效果收据，再结算数据库；崩溃后按同一收据核对，不能重新发出效果。
        self.journal.publish(receipt)

        if failpoint == "hard_after_receipt_before_settle":
            os._exit(92)
        if failpoint == "after_receipt_before_settle":
            raise SimulatedCrash("crash after durable receipt, before TX-Settle")
        return receipt

    def execute(self, run_id: str, *, failpoint: str | None = None) -> dict[str, Any]:
        """驱动单个精确文件任务的准入、效果、结算和验收；已获 Ticket 的机会不可盲重放。"""

        run = self.store.get_run(run_id)
        if run["state"] == RunState.SUCCEEDED.value:
            return self.status(run_id)

        attempt = self.store.get_attempt_for_run(run_id)
        if attempt["state"] == AttemptState.INTENT.value:
            ticket = self.store.start_attempt(attempt["attempt_id"], self._id("tkt"))
            attempt = self.store.get_attempt_for_run(run_id)
        elif attempt["state"] == AttemptState.TICKETED.value:
            raise RecoveryRequired(
                "Attempt already has a Ticket; call recover() instead of redispatching"
            )
        elif attempt["state"] == AttemptState.RESOLVED.value:
            return self._verify_and_deliver(run_id)
        else:
            raise RecoveryRequired(
                f"Attempt is {attempt['state']}; reconcile before continuing"
            )

        receipt = self._execute_ticket(run_id, attempt, ticket, failpoint)
        self.store.settle_receipt(receipt, usage_known=True)
        return self._verify_and_deliver(run_id)

    def recover(
        self, run_id: str | None = None, *, deliver: bool = True
    ) -> list[dict[str, Any]]:
        """用已有请求、Ticket、收据和对象核对执行状态；没有足够事实时保留 UNKNOWN，不盲目重发。"""

        recovered: list[dict[str, Any]] = []
        for attempt in self.store.get_pending_attempts(run_id):
            rid = str(attempt["run_id"])
            # Agent 的恢复只补执行事实；不能绕过其固定目标验收发布 P1 Delivery。
            has_agents = self.store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='agent_runs'"
            ).fetchone()
            agent_owned = (
                has_agents
                and self.store.db.execute(
                    "SELECT 1 FROM agent_runs WHERE run_id=?", (rid,)
                ).fetchone()
            )
            can_deliver = deliver and not agent_owned
            action = self.store.get_action(attempt["action_id"])
            journaled = self.journal.read(attempt["attempt_id"])
            if journaled is not None:
                if journaled.envelope_digest != attempt["envelope_digest"]:
                    raise RecoveryRequired(
                        "journal receipt belongs to a different envelope"
                    )
                self.store.settle_receipt(journaled, usage_known=True)
                recovered.append(
                    self._verify_and_deliver(rid)
                    if can_deliver
                    else {"attempt_id": attempt["attempt_id"], "state": "RESOLVED"}
                )
                continue

            path = self.workspaces.path_for(rid, action["target_name"])
            current_digest = sha256_bytes(path.read_bytes())
            if current_digest == action["after_digest"]:
                receipt = ReceiptData(
                    receipt_id=self._id("rcpt_reconcile"),
                    attempt_id=attempt["attempt_id"],
                    envelope_digest=attempt["envelope_digest"],
                    outcome=Outcome.SUCCEEDED,
                    evidence_ref=f"reconciled:{rid}/{action['target_name']}@{current_digest}",
                    usage={},
                )
                self.store.settle_receipt(receipt, usage_known=False)
                recovered.append(
                    self._verify_and_deliver(rid)
                    if can_deliver
                    else {"attempt_id": attempt["attempt_id"], "state": "RESOLVED"}
                )
            else:
                self.store.mark_attempt_unknown(
                    attempt["attempt_id"],
                    "Ticket exists but no durable receipt and managed content does not prove the expected effect",
                )
                recovered.append(
                    self.status(rid)
                    if can_deliver
                    else {"attempt_id": attempt["attempt_id"], "state": "UNKNOWN"}
                )
        return recovered

    # 独立比较固定期望与当前字节，发布验证证据，再登记唯一交付；物理导出与 DB 事实分别可恢复。
    def _verify_and_deliver(self, run_id: str) -> dict[str, Any]:
        has_agents = self.store.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='agent_runs'"
        ).fetchone()
        if (
            has_agents
            and self.store.db.execute(
                "SELECT 1 FROM agent_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        ):
            raise RecoveryRequired("Agent delivery requires its fixed goal verifier")
        run = self.store.get_run(run_id)
        if run["state"] == RunState.SUCCEEDED.value:
            return self.status(run_id)

        action = self.store.get_action_for_run(run_id)
        attempt = self.store.get_attempt_for_run(run_id)
        if (
            attempt["state"] != AttemptState.RESOLVED.value
            or attempt["outcome"] != Outcome.SUCCEEDED.value
        ):
            raise RecoveryRequired(
                "successful execution fact is required before verification"
            )

        path = self.workspaces.path_for(run_id, action["target_name"])
        candidate_digest = sha256_bytes(path.read_bytes())
        verdict = (
            Verdict.PASS
            if candidate_digest == action["after_digest"]
            else Verdict.INCONCLUSIVE
        )
        report_id = self.store.create_verification_report(
            run_id=run_id,
            action_id=action["action_id"],
            candidate_digest=candidate_digest,
            acceptance_version=run["acceptance_version"],
            verdict=verdict,
            evidence_ref=f"sha256:{candidate_digest}",
        )
        if verdict is not Verdict.PASS:
            return self.status(run_id)

        delivery_id = self.store.deliver(
            run_id=run_id,
            action_id=action["action_id"],
            candidate_digest=candidate_digest,
            report_id=report_id,
        )
        delivery_doc = {
            "delivery_id": delivery_id,
            "run_id": run_id,
            "action_id": action["action_id"],
            "candidate_digest": candidate_digest,
            "verification_report_id": report_id,
            "managed_file": str(path),
        }
        atomic_write(
            self.runtime_dir / "deliveries" / f"{run_id}.json",
            json.dumps(
                delivery_doc,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ).encode("utf-8"),
        )
        return self.status(run_id)

    # 读取当前持久事实并生成状态投影；不得把模型 claim 当作已执行或已验收。
    def status(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        action = self.store.get_action_for_run(run_id)
        attempt = self.store.get_attempt_for_run(run_id)
        delivery = self.store.get_delivery(run_id)
        return {
            "run_id": run_id,
            "state": run["state"],
            "action_id": action["action_id"],
            "attempt_id": attempt["attempt_id"],
            "attempt_state": attempt["state"],
            "outcome": attempt["outcome"],
            "candidate_digest": action["after_digest"],
            "managed_file": str(
                self.workspaces.path_for(run_id, action["target_name"])
            ),
            "delivery": delivery,
            "budgets": self.store.get_accounts(run_id),
            "events": self.store.get_events(run_id),
        }
