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


# 实验阶段明确区分广度发现与深度加固；避免单一路线无限 DFS 把偶然局部最优堆成复杂架构。
class ExperimentPhase(StrEnum):
    DISCOVER = "discover"
    HARDEN = "harden"


# Disposable Experiment 只保存可复现输入/变更/证据身份；实验编排器本身不成为生产 Runtime 的长期依赖。
@dataclass(frozen=True)
class ExperimentCandidate:
    experiment_id: str
    hypothesis: str
    phase: ExperimentPhase
    changes: tuple[str, ...]
    parent_experiment_id: str | None = None
    frozen_suite_ref: str | None = None
    workspace_ephemeral: bool = True

    def __post_init__(self) -> None:
        if not self.experiment_id.strip() or not self.hypothesis.strip():
            raise ValueError("experiment id/hypothesis are required")
        if not self.changes:
            raise ValueError("experiment must declare at least one change")
        if not self.workspace_ephemeral:
            raise ValueError("research orchestration must remain disposable")


# Discovery 负责并行提出不同机制，Harden 只对已经有证据的候选深化；函数不运行实验或自动发布策略。
def experiment_frontier(
    candidates: tuple[ExperimentCandidate, ...],
    *,
    phase: ExperimentPhase,
) -> tuple[ExperimentCandidate, ...]:
    values = tuple(item for item in candidates if item.phase is phase)
    if phase is ExperimentPhase.DISCOVER:
        # 广度阶段按独立 hypothesis 去重，不让同一包装词重复占满实验预算。
        seen = set()
        result = []
        for item in values:
            key = (item.hypothesis.strip().lower(), item.changes)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return tuple(result)
    # 深化阶段必须来自某个已存在 lineage；无 parent 的“hardening”其实是未标注的新探索。
    ids = {item.experiment_id for item in candidates}
    return tuple(
        item
        for item in values
        if item.parent_experiment_id and item.parent_experiment_id in ids
    )
