"""Harness 效率控制的纯策略合同。
本模块不拥有 Run/Context/Artifact 状态，只对已测量事实做经济门控、可达性解释和有界恢复选择；调用方负责持久化事件。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import ceil
from typing import Mapping


# 优化机制的可观察结果；SKIPPED/DEFERRED/INELIGIBLE 与 FAILED 分开，避免“没触发”变成黑盒。
class OptimizationOutcome(StrEnum):
    # APPLIED：机制已按当前固定事实生效。
    APPLIED = "APPLIED"
    # SKIPPED：候选存在，但前置条件变化等原因明确跳过。
    SKIPPED = "SKIPPED"
    # DEFERRED：当前证据/回本期不足，留待后续重新判断。
    DEFERRED = "DEFERRED"
    # FALLBACK：优化路径放弃，调用方回到原始信息或原始执行路径。
    FALLBACK = "FALLBACK"
    # FAILED：优化机制自身失败；不能冒充底层任务失败。
    FAILED = "FAILED"
    # INELIGIBLE：当前事实证明机制不具备正收益或准入资格。
    INELIGIBLE = "INELIGIBLE"


# 一次优化经济判断的已测量输入；provider_visible_saving 只接受模型真正可见投影的节约量。
@dataclass(frozen=True)
class OptimizationEconomics:
    # mechanism_id：被评估机制的稳定身份。
    mechanism_id: str
    # provider_visible_saving_per_request：每个未来真实请求可省的已测量 Token/等价单位；缺测为 None。
    provider_visible_saving_per_request: int | None
    # upfront_cost：本次切换/摘要/构建的前置投入。
    upfront_cost: int = 0
    # outstanding_debt：此前优化尚未摊销的债务。
    outstanding_debt: int = 0
    # remaining_requests：当前任务预计剩余请求数；缺测不能补零。
    remaining_requests: int | None = None
    # requests_since_last_apply：距上次同机制生效的请求数，用于滞回。
    requests_since_last_apply: int | None = None
    # cooldown_requests：普通条件下再次生效前的最小请求间隔。
    cooldown_requests: int = 2
    # emergency_required：安全/窗口保护要求时允许越过普通经济门槛。
    emergency_required: bool = False

    def __post_init__(self) -> None:
        if not self.mechanism_id.strip():
            raise ValueError("mechanism_id is required")
        for name in ("upfront_cost", "outstanding_debt", "cooldown_requests"):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")
        for name in (
            "provider_visible_saving_per_request",
            "remaining_requests",
            "requests_since_last_apply",
        ):
            value = getattr(self, name)
            if value is not None and int(value) < 0:
                raise ValueError(f"{name} must be non-negative when measured")


# 经济门控的纯决定；None 代表无法由当前证据量测，不能补造为零。
@dataclass(frozen=True)
class OptimizationDecision:
    # mechanism_id：本次决定对应的机制身份。
    mechanism_id: str
    # outcome：明确的应用/跳过/延后等结果。
    outcome: OptimizationOutcome
    # reason_code：供事件、测试和 UI 稳定消费的机器原因码。
    reason_code: str
    # reason：面向维护者的解释文本，不参与授权。
    reason: str
    # breakeven_requests：按已测量成本计算的回本请求数。
    breakeven_requests: int | None = None
    # projected_net_saving：当前 horizon 下的净节约估计；缺测保持 None。
    projected_net_saving: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "mechanism_id": self.mechanism_id,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "breakeven_requests": self.breakeven_requests,
            "projected_net_saving": self.projected_net_saving,
        }


# 只在“真实投影节约可测 + 剩余 horizon 可测 + 回本”时应用；窗口保护等安全约束可显式 emergency override。
def decide_optimization(economics: OptimizationEconomics) -> OptimizationDecision:
    if economics.emergency_required:
        return OptimizationDecision(
            economics.mechanism_id,
            OptimizationOutcome.APPLIED,
            "emergency_override",
            "safety/window protection requires the optimization regardless of ordinary payback",
        )
    saving = economics.provider_visible_saving_per_request
    horizon = economics.remaining_requests
    if saving is None or horizon is None:
        return OptimizationDecision(
            economics.mechanism_id,
            OptimizationOutcome.DEFERRED,
            "measurement_unavailable",
            "provider-visible saving or remaining request horizon is not measured",
        )
    if saving <= 0:
        return OptimizationDecision(
            economics.mechanism_id,
            OptimizationOutcome.INELIGIBLE,
            "no_positive_provider_visible_saving",
            "the executable provider-visible projection has no positive saving",
            breakeven_requests=None,
            projected_net_saving=0,
        )
    since = economics.requests_since_last_apply
    if (
        since is not None
        and since < economics.cooldown_requests
        and economics.cooldown_requests > 0
    ):
        return OptimizationDecision(
            economics.mechanism_id,
            OptimizationOutcome.DEFERRED,
            "cooldown_active",
            "recent application is inside the hysteresis window",
        )
    investment = economics.upfront_cost + economics.outstanding_debt
    breakeven = 0 if investment == 0 else ceil(investment / saving)
    net = saving * horizon - investment
    if horizon >= breakeven and net > 0:
        return OptimizationDecision(
            economics.mechanism_id,
            OptimizationOutcome.APPLIED,
            "positive_amortized_return",
            "measured future saving exceeds upfront cost and outstanding optimization debt",
            breakeven_requests=breakeven,
            projected_net_saving=net,
        )
    return OptimizationDecision(
        economics.mechanism_id,
        OptimizationOutcome.DEFERRED,
        "horizon_below_breakeven",
        "the remaining measured horizon cannot repay this optimization yet",
        breakeven_requests=breakeven,
        projected_net_saving=net,
    )


# 启用不等于可达；available/exposed/reachable 分开用于 Runtime Observatory 解释“为什么没有触发”。
@dataclass(frozen=True)
class MechanismReachability:
    # mechanism_id：机制稳定身份。
    mechanism_id: str
    # enabled：策略是否允许使用，不代表实现或工具面已经可达。
    enabled: bool
    # available：当前 Runtime 是否具有对应实现。
    available: bool
    # exposed：当前模型/工具面是否能触发该实现。
    exposed: bool
    # reachable：enabled、available、exposed 同时成立后的派生事实。
    reachable: bool
    # reason_code：不可达或可达的稳定解释码。
    reason_code: str

    def as_dict(self) -> dict[str, object]:
        return {
            "mechanism_id": self.mechanism_id,
            "enabled": self.enabled,
            "available": self.available,
            "exposed": self.exposed,
            "reachable": self.reachable,
            "reason_code": self.reason_code,
        }


# 从四个正交事实生成可达性；不因为 enabled=True 就假装当前模型/工具面能够触发机制。
def assess_reachability(
    mechanism_id: str,
    *,
    enabled: bool,
    available: bool,
    exposed: bool,
) -> MechanismReachability:
    if not enabled:
        code = "disabled"
    elif not available:
        code = "implementation_unavailable"
    elif not exposed:
        code = "surface_not_exposed"
    else:
        code = "reachable"
    return MechanismReachability(
        mechanism_id=mechanism_id,
        enabled=enabled,
        available=available,
        exposed=exposed,
        reachable=enabled and available and exposed,
        reason_code=code,
    )


# 恢复阶梯把“表达错误、变换错误、证据缺失、未知外部效果”分开，避免所有失败都支付同样昂贵的重做成本。
class RecoveryFailure(StrEnum):
    # REPRESENTATION：证据可能正确，但编码/引用/格式表达错误。
    REPRESENTATION = "representation"
    # TRANSFORMATION：压缩、摘要等变换本身未通过验证。
    TRANSFORMATION = "transformation"
    # EVIDENCE：支撑结论的来源证据缺失或失效。
    EVIDENCE = "evidence"
    # EXECUTION：底层执行已知失败，不等同结果不明。
    EXECUTION = "execution"
    # UNKNOWN：外部效果是否发生不明确，必须先核对。
    UNKNOWN = "unknown"


# 有界恢复阶梯的下一动作；恢复动作不授予新的 Capability。
class RecoveryAction(StrEnum):
    # REPAIR：只修正表达，不重新获取证据。
    REPAIR = "repair"
    # RETRY_TRANSFORMATION：在同一来源上重做有界变换。
    RETRY_TRANSFORMATION = "retry_transformation"
    # REACQUIRE_EVIDENCE：重新读取/获取来源证据。
    REACQUIRE_EVIDENCE = "reacquire_evidence"
    # FALLBACK_ORIGINAL：放弃优化，恢复原始来源/路径。
    FALLBACK_ORIGINAL = "fallback_original"
    # RECONCILE：先核对未知外部效果，禁止盲重放。
    RECONCILE = "reconcile"


# 有界恢复预算；每一级都有硬上限，保证不会因优化失败形成无限自修复循环。
@dataclass(frozen=True)
class RecoveryBudget:
    # repair_attempts：已消费的轻量表达修复次数。
    repair_attempts: int = 0
    # transformation_attempts：已消费的变换重试次数。
    transformation_attempts: int = 0
    # max_repairs：轻量修复硬上限。
    max_repairs: int = 1
    # max_transformations：变换重试硬上限。
    max_transformations: int = 1
    # can_reacquire：当前权限/来源是否允许重新取证。
    can_reacquire: bool = True

    def __post_init__(self) -> None:
        for value in (
            self.repair_attempts,
            self.transformation_attempts,
            self.max_repairs,
            self.max_transformations,
        ):
            if value < 0:
                raise ValueError("recovery counters must be non-negative")


# UNKNOWN 永远先 reconcile；有证据但表达坏优先廉价修复，证据本身坏才升级到重新取证。
def next_recovery_action(
    failure: RecoveryFailure, budget: RecoveryBudget
) -> RecoveryAction:
    if failure is RecoveryFailure.UNKNOWN:
        return RecoveryAction.RECONCILE
    if failure is RecoveryFailure.REPRESENTATION:
        if budget.repair_attempts < budget.max_repairs:
            return RecoveryAction.REPAIR
        if budget.transformation_attempts < budget.max_transformations:
            return RecoveryAction.RETRY_TRANSFORMATION
        return RecoveryAction.FALLBACK_ORIGINAL
    if failure is RecoveryFailure.TRANSFORMATION:
        if budget.transformation_attempts < budget.max_transformations:
            return RecoveryAction.RETRY_TRANSFORMATION
        return (
            RecoveryAction.REACQUIRE_EVIDENCE
            if budget.can_reacquire
            else RecoveryAction.FALLBACK_ORIGINAL
        )
    if failure is RecoveryFailure.EVIDENCE:
        return (
            RecoveryAction.REACQUIRE_EVIDENCE
            if budget.can_reacquire
            else RecoveryAction.FALLBACK_ORIGINAL
        )
    return RecoveryAction.FALLBACK_ORIGINAL


# 把机制门控事件编码成持久事件 payload；调用方决定写入哪个现有 Event log，不创建第二份状态仓储。
def optimization_event(
    *,
    mechanism_id: str,
    outcome: OptimizationOutcome,
    reason_code: str,
    metrics: Mapping[str, int | float | None] | None = None,
) -> dict[str, object]:
    return {
        "mechanism_id": mechanism_id,
        "outcome": outcome.value,
        "reason_code": reason_code,
        "metrics": dict(metrics or {}),
    }


# 只从已经持久化的 activity 识别可压缩语义边界候选；返回 None 表示不能证明一个工作片段已稳定落地。
def semantic_boundary(activity: Mapping[str, object]) -> str | None:
    result = activity.get("result")
    if not isinstance(result, Mapping):
        return None
    capability = activity.get("capability")
    decision = activity.get("decision")
    if not capability and isinstance(decision, Mapping):
        capability = decision.get("capability_id")
    if capability == "test.run" and result.get("status") in {"PASSED", "FAILED"}:
        return "verification_settled"
    if isinstance(result.get("artifact"), Mapping) and result.get("evidence_ref"):
        return "artifact_settled"
    subagent = result.get("subagent")
    if isinstance(subagent, Mapping) and result.get("evidence_bus"):
        return "delegation_settled"
    return None
