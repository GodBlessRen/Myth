"""通用对话循环：Control Plane 只在安全点改变未来工作，工具效果仍走持久执行端口。"""

from ..acceptance import ContextBudgetError
from ..domain import BudgetExceeded, RecoveryRequired
from ..models import StepDecision, DecisionValidationError
from ..conversation_ports import ConversationRepository, ConversationExecution


class ConversationAgent:
    def __init__(self, repository: ConversationRepository, execution: ConversationExecution, *, control, memory):
        self.repository = repository
        self.execution = execution
        self.control = control
        self.memory = memory

    def _gate(self, run_id: str) -> bool:
        return self.control.gate(run_id) is not None

    def run(self, run_id, provider):
        with self.execution.lock(run_id):
            turn = self.repository.turn(run_id)
            if turn["status"] == "PAUSED":
                return
            if turn["status"] not in {"RUNNING", "UNKNOWN"}:
                return
            if provider.provider_id != turn["settings"]["provider"]:
                raise ValueError("provider differs from fixed turn")
            if self._gate(run_id):
                return
            if not self.execution.recover(run_id):
                self.repository.block(
                    run_id,
                    "UNKNOWN",
                    "模型或工具已获执行凭证，但结果尚不明确；不会自动重发。",
                )
                return
            self.repository.reopen(run_id)

            while self.repository.turn(run_id)["status"] == "RUNNING":
                if self._gate(run_id):
                    return
                step = self.repository.begin_step(run_id)
                if step is None:
                    self.repository.block(
                        run_id,
                        "BUDGET_EXHAUSTED",
                        "本轮达到步数上限，可开始新一轮继续。",
                    )
                    return
                try:
                    turn = self.repository.turn(run_id)
                    turn["control"] = self.control.view(run_id)
                    if step.get("decision"):
                        decision_id, decision = step["decision_id"], StepDecision(**step["decision"])
                    else:
                        decision_id, decision = self.execution.decide(turn, step["step"], provider)
                        self.repository.bind(run_id, step["step"], decision_id, decision)
                        self.control.consume_compaction(run_id, decision_id=decision_id)

                    # A pause/abort arriving while the model was in flight is
                    # observed here before any newly proposed tool is launched.
                    if self._gate(run_id):
                        return

                    if decision.decision_type == "tool_call":
                        result = self.execution.execute(turn, decision_id, decision)
                        self.repository.finish_tool(run_id, step["step"], result)
                        if self._gate(run_id):
                            return
                    elif decision.decision_type == "ask_user":
                        self.repository.finish_reply(
                            run_id,
                            step["step"],
                            decision.question,
                            decision_id,
                        )
                        return
                    else:
                        self.repository.finish_reply(run_id, step["step"], decision.claim)
                        completed = self.repository.turn(run_id)
                        self.memory.record_episode(
                            run_id,
                            completed["snapshot"]["messages"][-1]["content"],
                            decision.claim or "",
                        )
                        return
                except ContextBudgetError as exc:
                    self.repository.block(run_id, "FAILED", str(exc))
                    return
                except (DecisionValidationError, ValueError, PermissionError) as exc:
                    self.repository.reject(run_id, step["step"], str(exc))
                except BudgetExceeded as exc:
                    self.repository.block(run_id, "BUDGET_EXHAUSTED", str(exc))
                    return
                except (RecoveryRequired, OSError, RuntimeError) as exc:
                    self.repository.block(run_id, "UNKNOWN", str(exc))
                    return
