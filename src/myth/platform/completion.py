"""Conversation 的 Verify-on-Stop 纯策略。
模型只能提出 completion；remaining、伪造证据或最近一次失败验证会把停止请求退回为 Observation。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..failures import FailureObservation, failure_result
from .model_pool import pending_reviews


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


# CompletionGuard：只检查可确定的停止前置条件；不会自行执行测试、调用模型或修改 Acceptance。
class CompletionGuard:
    # 核对未完成项、证据引用和已经运行过的 verifier；没有 verifier 时不凭空要求一个。
    def evaluate(self, turn: dict[str, Any], decision: Any) -> CompletionVerdict:
        pending = pending_reviews(turn.get("activities") or [])
        if pending:
            return CompletionVerdict(False, FailureObservation(
                "verification", "subagent_review_pending", "子任务尚未由主模型评分", True,
                hint="先调用 agent.evaluate，delegation_id: " + ", ".join(pending),
            ))
        remaining = tuple(getattr(decision, "remaining", ()) or ())
        if remaining:
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

        cited = tuple(getattr(decision, "evidence_refs", ()) or ())
        if cited:
            available = _observed_refs(
                {
                    "snapshot": turn.get("snapshot") or {},
                    "activities": turn.get("activities") or [],
                }
            )
            unknown = [ref for ref in cited if ref not in available]
            if unknown:
                return CompletionVerdict(
                    False,
                    FailureObservation(
                        "verification",
                        "completion_evidence_unknown",
                        "completion rejected: cited evidence is not present in durable observations",
                        True,
                        expected="evidence_refs must reference sources/receipts already observed in this Run",
                        hint="Use durable evidence_refs returned by tools/retrieval, or omit unsupported references.",
                    ),
                )

        verification_results = []
        for activity in turn.get("activities") or []:
            decision_data = activity.get("decision") or {}
            if decision_data.get("capability_id") != "test.run":
                continue
            result = activity.get("result") or {}
            if result:
                verification_results.append(result)
        if verification_results and verification_results[-1].get("status") != "PASSED":
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

        return CompletionVerdict(True)
