"""Conversation 的 Verify-on-Stop 纯策略。
模型只能提出 completion；remaining、伪造证据或最近一次失败验证会把停止请求退回为 Observation。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..failures import FailureObservation, failure_result
from .model_pool import pending_reviews, pending_resolutions


# 只有真正产生交付效果的 Conversation 工具进入 follow-through；读取/分析失败可由模型改走别的证据路径。
# test.run 保持下面独立的严格 PASS 规则，不使用一次性提醒降级验收。
_FOLLOWTHROUGH_CAPABILITIES = frozenset({"artifact.write", "project.patch_exact"})


# CompletionVerdict：停止准入结果；拒绝只要求下一步修正，不把已知拒绝升级成 UNKNOWN。
@dataclass(frozen=True)
class CompletionVerdict:
    # allowed：当前 completion proposal 是否可结束 Conversation Loop。
    allowed: bool
    # observation：拒绝时的结构化失败；允许时为空。
    observation: FailureObservation | None = None

    # 转换为步骤 Observation；只有拒绝分支可调用。
    def result(self) -> dict[str, Any]:
        if self.observation is None:
            raise ValueError("allowed completion has no rejection observation")
        return failure_result(self.observation, observation_kind="completion_guard")


# 从任意持久投影递归收集已经出现的来源/证据身份；只认字段值，不从文本猜引用。
def _observed_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    stack: list[tuple[str, Any]] = [("", value)]
    while stack:
        key, item = stack.pop()
        if isinstance(item, dict):
            stack.extend((str(child_key), child) for child_key, child in item.items())
        elif isinstance(item, (list, tuple)):
            stack.extend((key, child) for child in item)
        elif (
            isinstance(item, str)
            and item
            and key in {"evidence_ref", "source_ref", "citation"}
        ):
            refs.add(item)
    return refs


# 找到最近仍未被后续成功覆盖的“可恢复效果失败”。同一失败只强制一次 follow-through，避免错误恢复形成死循环。
def _pending_effect_followthrough(activities: list[dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    unresolved: dict[str, tuple[int, dict[str, Any]]] = {}
    reminded_at: dict[str, int] = {}
    for index, activity in enumerate(activities):
        result = activity.get("result") if isinstance(activity, dict) else None
        result = result if isinstance(result, dict) else {}
        failure = result.get("failure") if isinstance(result.get("failure"), dict) else None
        if (
            result.get("observation_kind") == "completion_guard"
            and failure
            and failure.get("code") == "completion_followthrough_required"
        ):
            capability = str(failure.get("capability_id") or "")
            if capability:
                reminded_at[capability] = index
            continue

        decision = activity.get("decision") if isinstance(activity, dict) else None
        decision = decision if isinstance(decision, dict) else {}
        capability = str(decision.get("capability_id") or "")
        if capability not in _FOLLOWTHROUGH_CAPABILITIES:
            continue
        if failure and bool(failure.get("retryable")):
            unresolved[capability] = (index, failure)
        elif result:
            # 后续同能力出现已知非失败结果，说明这次恢复机会已经真正闭合。
            unresolved.pop(capability, None)

    pending = [
        (index, capability, failure)
        for capability, (index, failure) in unresolved.items()
        if reminded_at.get(capability, -1) < index
    ]
    if not pending:
        return None
    _index, capability, failure = max(pending, key=lambda item: item[0])
    return capability, failure


# 每条 completion rule 只回答“当前能否继续停止”；返回 None 表示把判断交给下一条规则。
# 规则保持固定顺序，使新增约束不扩大 CompletionGuard 的公开 interface。
def _pending_review_rule(turn: dict[str, Any], decision: Any) -> CompletionVerdict | None:
    pending = pending_reviews(turn.get("activities") or [])
    if not pending:
        return None
    return CompletionVerdict(False, FailureObservation(
        "verification", "subagent_review_pending", "子任务尚未由主模型评分", True,
        hint="先调用 agent.evaluate，delegation_id: " + ", ".join(pending),
    ))


# 先拒绝仍需主模型处理的子任务拒收，避免未解决结果被完成声明覆盖。
def _pending_resolution_rule(turn: dict[str, Any], decision: Any) -> CompletionVerdict | None:
    unresolved = pending_resolutions(turn.get("activities") or [])
    if not unresolved:
        return None
    return CompletionVerdict(False, FailureObservation(
        "verification", "subagent_rejection_unresolved", "拒收的子任务尚无替代结果", True,
        hint="用 agent.resolve 自行补做，或用 replaces 重新委派并评分通过：" + ", ".join(unresolved),
    ))


# 模型自己声明 remaining 时必须继续工作；文字 completion 不能覆盖显式未完成项。
def _remaining_work_rule(turn: dict[str, Any], decision: Any) -> CompletionVerdict | None:
    remaining = tuple(getattr(decision, "remaining", ()) or ())
    if not remaining:
        return None
    return CompletionVerdict(
        False,
        FailureObservation(
            "verification",
            "completion_remaining",
            "completion rejected: the model still reports unfinished work",
            True,
            hint="Finish or explicitly resolve every remaining item before requesting completion again.",
        ),
    )


# 可恢复写效果失败必须至少经历一次后续处理；不在 Guard 内自动重试外部效果。
def _effect_followthrough_rule(turn: dict[str, Any], decision: Any) -> CompletionVerdict | None:
    followthrough = _pending_effect_followthrough(turn.get("activities") or [])
    if followthrough is None:
        return None
    capability, failure = followthrough
    return CompletionVerdict(
        False,
        FailureObservation(
            "execution",
            "completion_followthrough_required",
            f"completion rejected: {capability} has a recoverable failure with no later successful result",
            True,
            capability,
            expected="correct the effect attempt or explicitly reassess the blocker before completing",
            hint=(
                str(failure.get("hint") or "").strip()
                or "Use the durable failure observation to correct the effect attempt before claiming completion."
            ),
        ),
    )


# 完成声明引用的证据必须已存在于持久 Observation；禁止凭文本制造新 evidence ref。
def _evidence_rule(turn: dict[str, Any], decision: Any) -> CompletionVerdict | None:
    cited = tuple(getattr(decision, "evidence_refs", ()) or ())
    if not cited:
        return None
    available = _observed_refs({
        "snapshot": turn.get("snapshot") or {},
        "activities": turn.get("activities") or [],
    })
    unknown = [ref for ref in cited if ref not in available]
    if not unknown:
        return None
    return CompletionVerdict(
        False,
        FailureObservation(
            "verification",
            "completion_evidence_unknown",
            "completion rejected: cited evidence is not present in durable observations",
            True,
            expected="evidence_refs must reference sources/receipts already observed in this Run",
            hint="Use only durable evidence_refs returned by tools/retrieval; unsupported references must be removed rather than invented.",
        ),
    )


# 已实际运行 verifier 时只接受最新 PASS；未运行 verifier 不在此凭空新增验收要求。
def _verification_rule(turn: dict[str, Any], decision: Any) -> CompletionVerdict | None:
    verification_results = []
    for activity in turn.get("activities") or []:
        decision_data = activity.get("decision") or {}
        if decision_data.get("capability_id") != "test.run":
            continue
        result = activity.get("result") or {}
        if result:
            verification_results.append(result)
    if not verification_results or verification_results[-1].get("status") == "PASSED":
        return None
    return CompletionVerdict(
        False,
        FailureObservation(
            "verification",
            "verification_not_passed",
            "completion rejected: the latest executed verification did not pass",
            True,
            "test.run",
            expected="latest test.run status=PASSED",
            hint="Fix the verified failure and run the trusted verification profile again before requesting completion.",
        ),
    )


# 顺序即产品语义：更早的 durable blocker 优先暴露；外部调用方仍只看到 evaluate(turn, decision)。
_COMPLETION_RULES = (
    _pending_review_rule,
    _pending_resolution_rule,
    _remaining_work_rule,
    _effect_followthrough_rule,
    _evidence_rule,
    _verification_rule,
)


# CompletionGuard：把停止条件藏在一个深 module 后；新增规则不要求 ConversationAgent 了解内部顺序。
class CompletionGuard:
    # 依次执行纯规则；第一条拒绝即返回，全部通过才允许结束，不执行 I/O 或修改 Acceptance。
    def evaluate(self, turn: dict[str, Any], decision: Any) -> CompletionVerdict:
        for rule in _COMPLETION_RULES:
            verdict = rule(turn, decision)
            if verdict is not None:
                return verdict
        return CompletionVerdict(True)
