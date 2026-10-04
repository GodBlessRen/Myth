"""小型组件上下文的纯预算投影器。
用于架构合同和离线检验；真实对话的优先级、折叠和来源报告由 conversation_context 实现，二者不共占业务状态。"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Mapping


# 上下文候选片段；来源、优先级和必需标记属于投影规则，不授予权限。
@dataclass(frozen=True)
class ContextItem:
    # source_ref：固定资料/对象/Run 来源身份；分辨率改变时保留原来源。
    source_ref: str
    # content：上下文或消息正文；属于数据，不授予 Runtime 权限。
    content: str
    # priority：上下文装箱优先级；数值较大优先，required 另优先。
    priority: int = 0
    # required：是否必须保留；放不下时提前失败，不偷偷丢关键约束。
    required: bool = False


# 已选片段与预算使用的不可变投影；保留未选来源，不删除原始事实。
@dataclass(frozen=True)
class ContextFrame:
    # items：实际选入上下文片段；原始事实不在此删除。
    items: tuple[ContextItem, ...]
    # dropped：未选入来源身份集合；用于解释投影预算。
    dropped: tuple[str, ...]
    # bytes_used：所选 UTF-8 字节数；不是供应商 Token 用量。
    bytes_used: int
    # max_bytes：本地 UTF-8 字节上限；不是准确 tokenizer 窗口。
    max_bytes: int


# 按 required/priority 的确定性字节装箱器；必需内容放不下显式失败。
class ContextCompiler:
    # 按 required 和 priority 稳定装箱 UTF-8 字节；必需项放不下拒绝，可选项留 dropped 引用。
    def compile(self, items: list[ContextItem], *, max_bytes: int) -> ContextFrame:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        chosen: list[ContextItem] = []
        dropped: list[str] = []
        used = 0
        ordered = sorted(
            enumerate(items),
            key=lambda pair: (not pair[1].required, -pair[1].priority, pair[0]),
        )
        for _, item in ordered:
            size = len(item.content.encode("utf-8"))
            if item.required and used + size > max_bytes:
                raise ValueError(f"required context exceeds budget: {item.source_ref}")
            if used + size <= max_bytes:
                chosen.append(item)
                used += size
            else:
                dropped.append(item.source_ref)
        return ContextFrame(tuple(chosen), tuple(dropped), used, max_bytes)


# 只从已持久化 Tool/Artifact/Verification/Sub-Agent 结果识别上下文语义边界；普通模型自述不能制造边界。
def context_boundary(activity: Mapping[str, object]) -> str | None:
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
    if isinstance(subagent, Mapping) and result.get("evidence_refs"):
        return "delegation_settled"
    return None


# 在 normal/compact 两个真实 provider-visible 投影之间选择；有同单位成本证据时按回本期判断，缺测保持 None。
def choose_context_mode(
    *,
    normal_bytes: int,
    compact_bytes: int | None,
    max_bytes: int,
    remaining_requests: int | None,
    previous_mode: str | None = None,
    manual_compact: bool = False,
    upfront_cost_bytes: int | None = None,
    outstanding_debt_bytes: int | None = None,
) -> dict[str, object]:
    if normal_bytes < 0 or max_bytes <= 0:
        raise ValueError("context byte counts must be non-negative and max_bytes positive")
    if compact_bytes is not None and compact_bytes < 0:
        raise ValueError("compact_bytes must be non-negative when measured")
    if remaining_requests is not None and remaining_requests < 0:
        raise ValueError("remaining_requests must be non-negative when measured")
    for value in (upfront_cost_bytes, outstanding_debt_bytes):
        if value is not None and value < 0:
            raise ValueError("context economics costs must be non-negative when measured")

    pressure = normal_bytes / max_bytes
    enter_threshold = 0.78
    exit_threshold = 0.62
    saving = None if compact_bytes is None else max(0, normal_bytes - compact_bytes)
    projected = (
        None
        if saving is None or remaining_requests is None
        else saving * remaining_requests
    )
    measured_debt = (
        None
        if upfront_cost_bytes is None or outstanding_debt_bytes is None
        else upfront_cost_bytes + outstanding_debt_bytes
    )
    breakeven_requests = (
        None
        if saving is None or saving <= 0 or measured_debt is None
        else ceil(measured_debt / saving)
    )
    projected_net = (
        None
        if projected is None or measured_debt is None
        else projected - measured_debt
    )

    def result(mode: str, outcome: str, reason_code: str) -> dict[str, object]:
        return {
            "mode": mode,
            "outcome": outcome,
            "reason_code": reason_code,
            "normal_bytes": normal_bytes,
            "compact_bytes": compact_bytes,
            "provider_visible_saving_bytes": saving,
            "remaining_requests": remaining_requests,
            "projected_saving_bytes": projected,
            "pressure": pressure,
            "enter_threshold": enter_threshold,
            "exit_threshold": exit_threshold,
            "upfront_cost_bytes": upfront_cost_bytes,
            "optimization_debt_bytes": outstanding_debt_bytes,
            "breakeven_requests": breakeven_requests,
            "projected_net_saving_bytes": projected_net,
        }

    if manual_compact:
        return result("compact", "APPLIED", "explicit_user_control")
    if compact_bytes is None:
        return result("normal", "INELIGIBLE", "no_settled_context_boundary")

    hold_compact = previous_mode == "compact" and pressure >= exit_threshold
    enter_compact = pressure >= enter_threshold
    if not enter_compact and not hold_compact:
        return result("normal", "DEFERRED", "below_context_pressure_threshold")
    if saving is None or saving <= 0:
        return result("normal", "INELIGIBLE", "no_provider_visible_saving")

    # 只有同单位 upfront/debt 真正测到时才进入经济门；缺测不是零债务。
    if (
        measured_debt is not None
        and projected_net is not None
        and projected_net < 0
        and pressure < 0.90
    ):
        return result("normal", "DEFERRED", "context_economics_not_repaid")

    return result(
        "compact",
        "APPLIED",
        "hysteresis_hold" if hold_compact and not enter_compact else "context_pressure",
    )
