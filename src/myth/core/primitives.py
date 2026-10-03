"""长期 Goal 的最小不可变合同。
只描述身份、意图和生命周期；进度与 Run 关联由个人状态仓储保存，策略不能借 Goal 扩大权限。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


# 长期 Goal 的显式生命周期；ACTIVE 才可准入未来工作，与进度 current_state 分开。
class GoalState(StrEnum):
    # ACTIVE：长期意图允许未来准入；每个 Run 仍需独立预算/能力检查。
    ACTIVE = "ACTIVE"
    # PAUSED：暂停未来派发；晚到调用仍保留真实收据。
    PAUSED = "PAUSED"
    # COMPLETED：长期意图明确完成；会话回答结束不能自动代表全部目标已验收。
    COMPLETED = "COMPLETED"
    # ARCHIVED：长期意图归档，未来不准入；保留历史证据。
    ARCHIVED = "ARCHIVED"


@dataclass(frozen=True)
class Goal:
    """不可变长期意图；可拥有多个先后 Run，进度和关联由个人仓储保存。"""

    # goal_id：长期意图身份；跨会话/Run 保持稳定，不授予执行权限。
    goal_id: str
    # title：用户可见标题；用于导航，不是验收规则。
    title: str
    # description：显式说明文本；不作为能力授权。
    description: str
    # state：本合同的当前生命周期/成熟度；以所属枚举解释，不混用 Run 与 Goal 状态。
    state: GoalState = GoalState.ACTIVE
