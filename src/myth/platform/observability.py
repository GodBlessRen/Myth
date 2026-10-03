"""事件事实的纯轨迹投影。
只汇总已记录事件；不拥有 Run 状态，不根据动画或文本猜测 Ticket、预算或验收事实。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# 已发生事件的纯投影合同；sequence 表示本 Run 的持久事件顺序。
@dataclass(frozen=True)
class TraceEvent:
    # sequence：本 Run 的持久事件序号，单调分配。
    sequence: int
    # layer：轨迹分类字段；沿用数据合同，不把分类变成强制执行层。
    layer: str
    # kind：当前合同的对象/记忆用途分类；需与所属枚举解释。
    kind: str
    # payload：事件/命令的数据负载；不得包含认证秘钥。
    payload: dict[str, Any]


# 根据已记录事件统计轨迹；未知事件数量是观测，不改变执行状态。
class TraceProjection:
    # 从真实已给事件统计类别、unknown 和最后序号；投影不修正业务状态。
    def summarize(self, events: list[TraceEvent]) -> dict[str, Any]:
        by_layer: dict[str, int] = {}
        unknown = 0
        for event in events:
            by_layer[event.layer] = by_layer.get(event.layer, 0) + 1
            if "unknown" in event.kind.lower():
                unknown += 1
        return {
            "events": len(events),
            "by_layer": dict(sorted(by_layer.items())),
            "unknown_events": unknown,
            "last_sequence": max((event.sequence for event in events), default=0),
        }
