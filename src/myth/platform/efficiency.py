"""Harness 效率控制的纯策略合同。
本模块不拥有 Run/Context/Artifact 状态，只对已测量事实做经济门控、可达性解释和有界恢复选择；调用方负责持久化事件。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import ceil
from typing import Mapping


# 优化机制的可观察结果；SKIPPED/DEFERRED/INELIGIBLE 与 FAILED 分开，避免“没触发”变成黑盒。
class OptimizationOutcome(StrEnum):
    APPLIED = "APPLIED"
    SKIPPED = "SKIPPED"
    DEFERRED = "DEFERRED"
    FALLBACK = "FALLBACK"
    FAILED = "FAILED"
    INELIGIBLE = "INELIGIBLE"


# 一次优化经济判断的已测量输入；provider_visible_saving 只接受模型真正可见投影的节约量。
@dataclass(frozen=True)
class OptimizationEconomics:
    mechanism_id: str
    provider_visible_saving_per_request: int | None
    upfront_cost: int = 0
    outstanding_debt: int = 0
    remaining_requests: int | None = None
    requests_since_last_apply: int | None = None
    cooldown_requests: int = 2
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
    mechanism_id: str
    outcome: OptimizationOutcome
    reason_code: str
    reason: str
    breakeven_requests: int | None = None
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
    mechanism_id: str
    enabled: bool
    available: bool
    exposed: bool
    reachable: bool
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
    REPRESENTATION = "representation"
    TRANSFORMATION = "transformation"
    EVIDENCE = "evidence"
    EXECUTION = "execution"
    UNKNOWN = "unknown"


class RecoveryAction(StrEnum):
    REPAIR = "repair"
    RETRY_TRANSFORMATION = "retry_transformation"
    REACQUIRE_EVIDENCE = "reacquire_evidence"
    FALLBACK_ORIGINAL = "fallback_original"
    RECONCILE = "reconcile"


# 有界恢复预算；每一级都有硬上限，保证不会因优化失败形成无限自修复循环。
@dataclass(frozen=True)
class RecoveryBudget:
    repair_attempts: int = 0
    transformation_attempts: int = 0
    max_repairs: int = 1
    max_transformations: int = 1
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
