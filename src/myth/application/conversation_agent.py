"""通用对话循环：Control Plane 只在安全点改变未来工作，工具效果仍走持久执行端口。"""

from ..acceptance import ContextBudgetError
from ..domain import BudgetExceeded, RecoveryRequired, PatchContractError
from ..models import StepDecision, DecisionValidationError
from ..conversation_ports import ConversationRepository, ConversationExecution


class ConversationAgent:
    def __init__(self, repository: ConversationRepository, execution: ConversationExecution, *, control, memory, personal=None):
        self.repository = repository
        self.execution = execution
        self.control = control
        self.memory = memory
        self.personal = personal

    def _checkpoint_goal(self, run_id: str, *, status: str, summary: str = "", next_action: str = "", waiting_for: str = "") -> None:
        if self.personal is None:
            return
        turn = self.repository.turn(run_id)
        goal = turn["snapshot"].get("goal") or {}
        goal_id = goal.get("goal_id")
        if not goal_id:
            return
        self.personal.checkpoint_run(
            goal_id,
            run_id,
            status=status,
            summary=summary,
            next_action=next_action,
            waiting_for=waiting_for,
        )

    def _gate(self, run_id: str) -> bool:
        return self.control.gate(run_id) is not None

    def run(self, run_id, provider):
        with self.execution.lock(run_id):
            turn = self.repository.turn(run_id)
            if turn["status"] == "PAUSED":
                return
            if turn["status"] not in {"RUNNING", "INTERRUPTED", "UNKNOWN"}:
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
                self._checkpoint_goal(run_id,status="UNKNOWN",summary="Execution receipt is unresolved.",next_action="Reconcile the uncertain attempt before continuing.")
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
                    self._checkpoint_goal(run_id,status="BUDGET_EXHAUSTED",summary="Turn step budget exhausted.",next_action="Review the unfinished work and admit a new turn.")
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
                        self._checkpoint_goal(
                            run_id,
                            status="WAITING_USER",
                            summary="Agent reached a decision point that requires user input.",
                            next_action="Resume after the user answers the pending question.",
                            waiting_for=decision.question or "user input",
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
                        self._checkpoint_goal(
                            run_id,
                            status="COMPLETED",
                            summary=(decision.claim or "")[:2000],
                            next_action="Review the result and continue the next unfinished part of this goal.",
                        )
                        return
                except ContextBudgetError as exc:
                    self.repository.block(run_id, "FAILED", str(exc))
                    self._checkpoint_goal(run_id,status="FAILED",summary=str(exc),next_action="Resolve the context-budget blocker before retrying.")
                    return
                except (DecisionValidationError, ValueError, PermissionError, PatchContractError) as exc:
                    self.repository.reject(run_id, step["step"], str(exc))
                except BudgetExceeded as exc:
                    self.repository.block(run_id, "BUDGET_EXHAUSTED", str(exc))
                    self._checkpoint_goal(run_id,status="BUDGET_EXHAUSTED",summary=str(exc),next_action="Start a new admitted turn with an adjusted budget.")
                    return
                except (RecoveryRequired, OSError, RuntimeError) as exc:
                    self.repository.block(run_id, "UNKNOWN", str(exc))
                    self._checkpoint_goal(run_id,status="UNKNOWN",summary=str(exc),next_action="Reconcile the uncertain attempt before any replay.")
                    return
