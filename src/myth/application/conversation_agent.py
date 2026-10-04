"""Conversation 与长期 Goal 的应用循环。
通过五类端口协调状态、I/O、控制、记忆及进度；安全点控制未来派发，COMPLETED 仅表示回答结束，不能升级为语义验收。"""

from ..acceptance import ContextBudgetError
from ..domain import BudgetExceeded, RecoveryRequired, PatchContractError
from ..failures import failure_result, observe_failure
from ..models import StepDecision, DecisionValidationError, ProviderKnownFailure, ProviderUnavailable
from ..platform.completion import CompletionGuard
from ..conversation_ports import (
    ConversationRepository,
    ConversationExecution,
    ConversationControl,
    ConversationMemory,
    GoalCheckpoint,
    ConversationDelivery,
)


# 只依赖端口的对话编排器；Control、Memory、Personal 协作各自保留状态所有权。
class ConversationAgent:
    # 接收五类可替换端口；应用不取得 SQL/具体供应商，长期 checkpoint 可缺省，终结后协作提交各自状态。
    def __init__(
        self,
        repository: ConversationRepository,
        execution: ConversationExecution,
        *,
        control: ConversationControl,
        memory: ConversationMemory,
        personal: GoalCheckpoint | None = None,
        delivery: ConversationDelivery | None = None,
    ):
        # repository：用例仓储端口/实现；持久状态写入归此协作对象所有。
        self.repository = repository
        # execution：用例执行端口/实现；外部效果须经过 Ticket 和收据协议。
        self.execution = execution
        # control：控制服务协作对象；只在安全点影响未来规划。
        self.control = control
        # memory：有来源记忆协作对象；不授予权限。
        self.memory = memory
        # personal：长期意图及进度的状态所有者；对话准入通过显式事务协作加入。
        self.personal = personal
        # delivery：交付事实所有者；COMPLETED 不自动等于语义验收通过。
        self.delivery = delivery
        # completion_guard：Verify-on-Stop 纯策略；不执行测试，只核对现有 durable evidence。
        self.completion_guard = CompletionGuard()

    # 按 Turn 冻结 Goal 身份写长期进度；个人仓储负责拒绝旧 Run 的迟到覆盖。
    def _checkpoint_goal(
        self,
        run_id: str,
        *,
        status: str,
        summary: str = "",
        next_action: str = "",
        waiting_for: str = "",
    ) -> None:
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

    # 查询控制安全点并返回是否停止规划；控制不会撤销已签发外部调用。
    def _gate(self, run_id: str) -> bool:
        return self.control.gate(run_id) is not None

    # 锁定一个 Run，先核对旧机会，逐步复用/绑定决定；效果后保留收据，回答后分别记录经历和 Goal 进度。
    def run(self, run_id, provider):
        with self.execution.lock(run_id):
            turn = self.repository.turn(run_id)
            if self.delivery is not None:
                self.delivery.reconcile_pending(
                    self.repository, self.memory, self.personal, run_id=run_id, limit=1
                )
                turn = self.repository.turn(run_id)
                if turn["status"] in {"RUNNING", "INTERRUPTED", "UNKNOWN"}:
                    self.delivery.ensure_root_work_item(turn)
            if turn["status"] == "PAUSED":
                return
            if (turn.get("network_retry") or {}).get("remaining_seconds", 0) > 0:
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
                self._checkpoint_goal(
                    run_id,
                    status="UNKNOWN",
                    summary="Execution receipt is unresolved.",
                    next_action="Reconcile the uncertain attempt before continuing.",
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
                    self._checkpoint_goal(
                        run_id,
                        status="BUDGET_EXHAUSTED",
                        summary="Turn step budget exhausted.",
                        next_action="Review the unfinished work and admit a new turn.",
                    )
                    return
                capability_id = None
                try:
                    turn = self.repository.turn(run_id)
                    turn["control"] = self.control.view(run_id)
                    if step.get("decision"):
                        decision_id, decision = step["decision_id"], StepDecision(
                            **step["decision"]
                        )
                    else:
                        decision_id, decision = self.execution.decide(
                            turn, step["step"], provider
                        )
                        self.repository.bind(
                            run_id, step["step"], decision_id, decision
                        )
                        self.repository.network_restored(run_id)
                    capability_id = decision.capability_id
                        self.control.consume_compaction(run_id, decision_id=decision_id)

                    # 模型在途时到达的 Pause/Stop 在这里被观察；新工具派发前再次检查安全点。
                    if self._gate(run_id):
                        return

                    if decision.decision_type == "tool_call":
                        # Sub-Agent 需要复用本轮固定 Provider；是否委派仍完全来自当前模型决定。
                        if decision.capability_id == "agent.delegate":
                            result = self.execution.execute(
                                turn, decision_id, decision, provider=provider
                            )
                        else:
                            result = self.execution.execute(turn, decision_id, decision)
                        self.repository.finish_tool(run_id, step["step"], result)
                        if self.delivery is not None:
                            self.delivery.record_tool_result(run_id, result)
                        if self._gate(run_id):
                            return
                    elif decision.decision_type == "ask_user":
                        self.repository.finish_reply(
                            run_id,
                            step["step"],
                            decision.question,
                            decision_id,
                        )
                        if self.delivery is not None:
                            self.delivery.update_root_work_item(
                                run_id,
                                status="WAITING",
                                progress_note=decision.question or "Waiting for user input.",
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
                        stop_verdict = self.completion_guard.evaluate(
                            self.repository.turn(run_id), decision
                        )
                        if not stop_verdict.allowed:
                            self.repository.finish_observation(
                                run_id, step["step"], stop_verdict.result()
                            )
                            if self.delivery is not None:
                                self.delivery.update_root_work_item(
                                    run_id,
                                    status="RUNNING",
                                    progress_note=stop_verdict.observation.message,
                                )
                            continue
                        if self.delivery is not None:
                            goal = (turn.get("snapshot") or {}).get("goal") or {}
                            self.delivery.prepare_completion(
                                run_id,
                                decision.claim or "",
                                goal_id=goal.get("goal_id"),
                                goal_summary=(decision.claim or "")[:2000],
                                next_action="Review the result and continue the next unfinished part of this goal.",
                            )
                        self.repository.finish_reply(
                            run_id, step["step"], decision.claim
                        )
                        if self.delivery is not None:
                            self.delivery.mark_answer_committed(run_id)
                            self.delivery.reconcile_pending(
                                self.repository, self.memory, self.personal, run_id=run_id, limit=1
                            )
                        else:
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
                except ProviderUnavailable:
                    # 明确零派发收据已经结算；保留同一 step，退出线程等待后台按持久截止时间继续。
                    if not self._gate(run_id):
                        self.repository.defer_network(run_id)
                        self._checkpoint_goal(run_id, status="INTERRUPTED",
                            summary="Provider disconnected before dispatch; checkpoint preserved.",
                            next_action="Wait for the scheduled reconnection check.")
                    return
                except (ContextBudgetError, ProviderKnownFailure) as exc:
                    self.repository.block(run_id, "FAILED", str(exc))
                    self._checkpoint_goal(
                        run_id,
                        status="FAILED",
                        summary=str(exc),
                        next_action="Resolve the reported provider or context blocker before a new turn.",
                    )
                    return
                except (
                    DecisionValidationError,
                    ValueError,
                    PermissionError,
                    PatchContractError,
                ) as exc:
                    observation = observe_failure(exc, capability_id=capability_id)
                    self.repository.finish_observation(
                        run_id,
                        step["step"],
                        failure_result(observation),
                    )
                except BudgetExceeded as exc:
                    self.repository.block(run_id, "BUDGET_EXHAUSTED", str(exc))
                    self._checkpoint_goal(
                        run_id,
                        status="BUDGET_EXHAUSTED",
                        summary=str(exc),
                        next_action="Start a new admitted turn with an adjusted budget.",
                    )
                    return
                except (RecoveryRequired, OSError, RuntimeError) as exc:
                    self.repository.block(run_id, "UNKNOWN", str(exc))
                    self._checkpoint_goal(
                        run_id,
                        status="UNKNOWN",
                        summary=str(exc),
                        next_action="Reconcile the uncertain attempt before any replay.",
                    )
                    return
