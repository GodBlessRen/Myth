"""策略候选及人工发布决定的纯合同。
评测只给资格，不自动 Promote；活动策略替换由持久控制器提交且只影响未来准入。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .evaluation import EvalReport, release_gate


# 策略发布资格的纯结论；PROMOTE 表示可显式发布，不会自己修改活动指针。
class PromotionDecision(StrEnum):
    # PROMOTE：满足固定资格的发布提案；实际切换须显式调用发布仓储。
    PROMOTE = "promote"
    # HOLD：证据不足，保持候选研究状态。
    HOLD = "hold"
    # REJECT：观测到不允许的回归/条件，拒绝发布资格。
    REJECT = "reject"


# 声明策略变更的纯候选合同；不修改正在运行的 Runtime。
@dataclass(frozen=True)
class PolicyCandidate:
    # candidate_id：研究策略候选稳定身份；不直接拥有活动策略。
    candidate_id: str
    # baseline_version：候选声明的基准版本。
    baseline_version: str
    # candidate_version：候选声明的新版本。
    candidate_version: str
    # changes：显式声明的候选变更集合。
    changes: tuple[str, ...]


# 结合固定评测门槛和已声明变更给出资格；不修改任何活动指针。
def decide_promotion(
    candidate: PolicyCandidate, report: EvalReport
) -> tuple[PromotionDecision, str]:
    passed, reason = release_gate(report)
    if not passed:
        return PromotionDecision.HOLD, reason
    if not candidate.changes:
        return PromotionDecision.REJECT, "candidate contains no declared changes"
    return (
        PromotionDecision.PROMOTE,
        "eligible for explicit release; not auto-published",
    )
