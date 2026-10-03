"""同源信息 L0/L1/L2 的纯选择策略。
固定显式资料优先级与展开预算，配置派生控制器；策略返回投影计划，仓储冻结到 Turn 后不倒写历史。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from ..domains.information import InformationResolution, IntentRoute


# _DEEP_CUE：要求同源全文表示的规则线索；不是语义正确率测量。
_DEEP_CUE = re.compile(
    r"(?:原文|全文|详细|具体|逐字|证据|出处|展开|"
    r"full\s*text|detail|exact\s+wording|evidence|source\s+text)",
    re.IGNORECASE,
)


# 一次同源展开的不可变计划；来源数、字符数是预算，不是供应商 Token 保证。
@dataclass(frozen=True)
class ResolutionPlan:
    # resolution：同源表示等级 L0/L1/L2；不是语义置信度。
    resolution: InformationResolution
    # max_sources：最多来源数量；显式固定附件另保留代表来源。
    max_sources: int
    # max_chars_per_source：每来源投影 Unicode 字符上限，不是字节/Token。
    max_chars_per_source: int
    # reason：可解释的选择/拒绝原因；不是授权证据。
    reason: str

    # 生成 JSON 可保存的数据投影；保留身份、版本和单位，不在此授予执行或发布权限。
    def serializable(self) -> dict[str, Any]:
        return {
            "resolution": self.resolution.value,
            "max_sources": self.max_sources,
            "max_chars_per_source": self.max_chars_per_source,
            "reason": self.reason,
        }


# 按任务和固定资料选择分辨率的纯策略；不产生 I/O，也不改变来源摘要。
class RuleResolutionController:
    # strategy_id：组织策略身份；策略可替换而 Core 事实保持稳定。
    strategy_id = "information_resolution"

    # 依据明确可用性与预算选择策略；返回规划结果，不执行外部效果。
    def choose(
        self,
        text: str,
        *,
        route: IntentRoute,
        sources: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        attached_document_ids: list[str] | tuple[str, ...] = (),
    ) -> ResolutionPlan:
        if not sources:
            return ResolutionPlan(
                InformationResolution.L0,
                0,
                0,
                "no admitted local source is available",
            )
        if attached_document_ids:
            return ResolutionPlan(
                InformationResolution.L2,
                max(2, len(attached_document_ids)),
                6000,
                "explicitly attached documents deserve detailed source projection",
            )
        if _DEEP_CUE.search(str(text or "")):
            return ResolutionPlan(
                InformationResolution.L2,
                2,
                6000,
                "user requested detailed/source-level evidence",
            )
        if route is IntentRoute.LOCAL_RETRIEVAL:
            return ResolutionPlan(
                InformationResolution.L1,
                5,
                1800,
                "local-retrieval route needs navigable source chunks before deeper expansion",
            )
        return ResolutionPlan(
            InformationResolution.L0,
            5,
            500,
            "general Agent route receives lightweight source previews by default",
        )


class FixedResolutionController:
    """离线评测或显式发布的固定分辨率策略；已有 Turn 使用自己的冻结配置。"""

    # strategy_id：组织策略身份；策略可替换而 Core 事实保持稳定。
    strategy_id = "information_resolution"

    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
    def __init__(self, resolution: InformationResolution):
        # resolution：同源表示等级 L0/L1/L2；不是语义置信度。
        self.resolution = InformationResolution(resolution)

    # 依据明确可用性与预算选择策略；返回规划结果，不执行外部效果。
    def choose(
        self,
        text: str,
        *,
        route: IntentRoute,
        sources: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        attached_document_ids: list[str] | tuple[str, ...] = (),
    ) -> ResolutionPlan:
        if not sources:
            return ResolutionPlan(
                InformationResolution.L0, 0, 0, "no admitted local source is available"
            )
        chars = {
            InformationResolution.L0: 500,
            InformationResolution.L1: 1800,
            InformationResolution.L2: 6000,
        }[self.resolution]
        return ResolutionPlan(
            self.resolution,
            max(5, len(attached_document_ids)),
            chars,
            f"fixed promoted/eval resolution={self.resolution.value}",
        )


def resolution_controller_from_config(config: dict[str, Any] | None):
    """只解析小型 rule/fixed 配置，拒绝未知模式；配置可固定版本而不引入执行权限。"""
    value = dict(config or {"mode": "rule"})
    mode = str(value.get("mode") or "rule")
    if mode == "rule":
        return RuleResolutionController()
    if mode == "fixed":
        raw = str(value.get("resolution") or "").upper()
        return FixedResolutionController(InformationResolution(raw))
    raise ValueError("unsupported information_resolution policy mode")
