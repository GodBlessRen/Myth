"""有界单 Agent 驱动器；每步依据持久决策消费状态继续。

一项工具决策绑定一个业务 Action。崩溃后读取已有决定和收据，不能靠
内存游标猜测步骤已经执行。模型提案与可信目标验收分别处理。
"""
from __future__ import annotations
from ..acceptance import ContextBudgetError, compile_context, verify_goal
from ..domain import BudgetExceeded, PatchContractError, RecoveryRequired
from ..models import DecisionValidationError, StepDecision
from ..ports import AgentExecution, AgentRepository


class AgentDriver:
    def __init__(self, repository: AgentRepository, execution: AgentExecution) -> None:
        self.repository = repository
        self.execution = execution

    def run(self, run_id: str, provider) -> dict:
        with self.execution.lock(run_id):
            row = self.repository.row(run_id)
            if row["provider_id"] != provider.provider_id:
                raise ValueError("provider must match the provider fixed for this run")
            if row["status"] in {"SUCCEEDED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED", "WAITING_USER"}:
                return self.repository.status(run_id)
            if not self.execution.recover(run_id):
                self.repository.block(run_id, "UNKNOWN", "unresolved Ticket; durable outcome required before continuing")
                return self.repository.status(run_id)
            self.repository.reopen(run_id)
            while self.repository.row(run_id)["status"] == "RUNNING":
                step = self.repository.begin_step(run_id)
                if step is None:
                    self.repository.block(run_id, "BUDGET_EXHAUSTED", "max_steps reached without verified goal completion")
                    break
                number = step["step"]
                try:
                    if step["decision_json"]:
                        decision = StepDecision(**step["decision_json"])
                        decision_id = step["decision_id"]
                    else:
                        context = compile_context(self.repository.notes(run_id), self.repository.manifest(run_id))
                        decision_id, decision = self.execution.request_decision(run_id, number, provider, context)
                        self.repository.bind_decision(run_id, number, decision_id, decision)
                    # 控制命令可在模型 I/O 期间提交；结果仍保留，但取消后禁止创建工具意图。
                    if self.repository.row(run_id)["status"] != "RUNNING":
                        break
                    if decision.decision_type == "ask_user":
                        self.repository.finish_step(run_id, number, "question", {
                            "text": decision.question, "question_id": decision_id}, "WAITING_USER")
                        break
                    if decision.decision_type == "tool_call":
                        payload = self.execution.execute(run_id, decision_id, decision)
                        self.repository.finish_step(run_id, number, "tool_result", payload)
                        continue
                    candidate = self.execution.current(run_id)
                    verdict, reason = verify_goal(self.repository.manifest(run_id), candidate,
                                                  self.execution.evidence(run_id), tuple(decision.evidence_refs),
                                                  tuple(decision.remaining))
                    self.repository.verify_and_deliver(run_id, number, verdict.value, reason, decision, candidate)
                except (DecisionValidationError, PatchContractError, PermissionError) as exc:
                    self.repository.finish_step(run_id, number, "tool_rejected", {"error": str(exc)})
                except ContextBudgetError as exc:
                    self.repository.block(run_id, "FAILED", str(exc))
                    break
                except BudgetExceeded as exc:
                    self.repository.block(run_id, "BUDGET_EXHAUSTED", str(exc))
                    break
                except (RecoveryRequired, OSError, RuntimeError) as exc:
                    self.repository.block(run_id, "UNKNOWN", f"{type(exc).__name__}: {exc}")
                    break
                except ValueError as exc:
                    self.repository.finish_step(run_id, number, "tool_rejected", {"error": str(exc)})
            return self.repository.status(run_id)
