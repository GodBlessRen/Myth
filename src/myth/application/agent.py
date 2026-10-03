"""Exact Agent 的有界应用用例。
只通过仓储与执行端口协调步骤，恢复读取持久决定/收据；目标完成必须由固定验收证明，不直接持有数据库或具体供应商。"""

from __future__ import annotations
from ..acceptance import ContextBudgetError, compile_context, verify_goal
from ..domain import BudgetExceeded, PatchContractError, RecoveryRequired
from ..models import DecisionValidationError, StepDecision, ProviderKnownFailure, ProviderUnavailable
from ..ports import AgentExecution, AgentRepository


# Exact 用例的短生命周期编排器；借执行锁驱动一个 Run，状态与步骤全部来自仓储。
class AgentDriver:
    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
    def __init__(self, repository: AgentRepository, execution: AgentExecution) -> None:
        # repository：用例仓储端口/实现；持久状态写入归此协作对象所有。
        self.repository = repository
        # execution：用例执行端口/实现；外部效果须经过 Ticket 和收据协议。
        self.execution = execution

    # 先恢复旧模型/工具机会，再消费持久决定；只有固定字节验收 PASS 才调用交付入口。
    def run(self, run_id: str, provider) -> dict:
        with self.execution.lock(run_id):
            row = self.repository.row(run_id)
            if row["provider_id"] != provider.provider_id:
                raise ValueError("provider must match the provider fixed for this run")
            if row["status"] in {
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                "BUDGET_EXHAUSTED",
                "WAITING_USER",
            }:
                return self.repository.status(run_id)
            if not self.execution.recover(run_id):
                self.repository.block(
                    run_id,
                    "UNKNOWN",
                    "unresolved Ticket; durable outcome required before continuing",
                )
                return self.repository.status(run_id)
            self.repository.reopen(run_id)
            while self.repository.row(run_id)["status"] == "RUNNING":
                step = self.repository.begin_step(run_id)
                if step is None:
                    self.repository.block(
                        run_id,
                        "BUDGET_EXHAUSTED",
                        "max_steps reached without verified goal completion",
                    )
                    break
                number = step["step"]
                try:
                    if step["decision_json"]:
                        decision = StepDecision(**step["decision_json"])
                        decision_id = step["decision_id"]
                    else:
                        context = compile_context(
                            self.repository.notes(run_id),
                            self.repository.manifest(run_id),
                        )
                        decision_id, decision = self.execution.request_decision(
                            run_id, number, provider, context
                        )
                        self.repository.bind_decision(
                            run_id, number, decision_id, decision
                        )
                    # 控制命令可在模型 I/O 期间提交；结果仍保留，但取消后禁止创建工具意图。
                    if self.repository.row(run_id)["status"] != "RUNNING":
                        break
                    if decision.decision_type == "ask_user":
                        self.repository.finish_step(
                            run_id,
                            number,
                            "question",
                            {"text": decision.question, "question_id": decision_id},
                            "WAITING_USER",
                        )
                        break
                    if decision.decision_type == "tool_call":
                        payload = self.execution.execute(run_id, decision_id, decision)
                        self.repository.finish_step(
                            run_id, number, "tool_result", payload
                        )
                        continue
                    candidate = self.execution.current(run_id)
                    verdict, reason = verify_goal(
                        self.repository.manifest(run_id),
                        candidate,
                        self.execution.evidence(run_id),
                        tuple(decision.evidence_refs),
                        tuple(decision.remaining),
                    )
                    self.repository.verify_and_deliver(
                        run_id, number, verdict.value, reason, decision, candidate
                    )
                except (
                    DecisionValidationError,
                    PatchContractError,
                    PermissionError,
                ) as exc:
                    self.repository.finish_step(
                        run_id, number, "tool_rejected", {"error": str(exc)}
                    )
                except ProviderUnavailable as exc:
                    # Exact CLI 不拥有常驻调度器；保留原步骤，后续显式驱动可继续同 Run。
                    self.repository.block(run_id, "INTERRUPTED", str(exc))
                    break
                except (ContextBudgetError, ProviderKnownFailure) as exc:
                    self.repository.block(run_id, "FAILED", str(exc))
                    break
                except BudgetExceeded as exc:
                    self.repository.block(run_id, "BUDGET_EXHAUSTED", str(exc))
                    break
                except (RecoveryRequired, OSError, RuntimeError) as exc:
                    self.repository.block(
                        run_id, "UNKNOWN", f"{type(exc).__name__}: {exc}"
                    )
                    break
                except ValueError as exc:
                    self.repository.finish_step(
                        run_id, number, "tool_rejected", {"error": str(exc)}
                    )
            return self.repository.status(run_id)
