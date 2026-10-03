"""个人 Trigger 的纯合同。
只记录长期 Goal 的触发意图与版本化参数；实际计划准入由调度适配器实现，不能靠描述记录自动产生权限。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


# 显式触发来源类型；声明 cron/event 等不代表已有可执行适配器。
class TriggerKind(StrEnum):
    # USER：明确用户输入触发描述；不是模型自动授权。
    USER = "user"
    # TIMER：时间触发描述；具体可执行计划由 GoalScheduler 保存。
    TIMER = "timer"
    # SCHEDULE：计划触发描述；不把目录记录当作已运行机会。
    SCHEDULE = "schedule"
    # EVENT：事件触发描述；事件仍需正常业务准入。
    EVENT = "event"
    # WEBHOOK：Webhook 触发规划；尚无后端时不能宣称可执行。
    WEBHOOK = "webhook"
    # EMAIL：邮件触发规划；不因登记而获得发送/读取授权。
    EMAIL = "email"
    # FILE_CHANGE：文件变化触发规划；变化信息不是执行收据。
    FILE_CHANGE = "file_change"
    # AGENT_EVENT：Agent 事件触发描述；父授权和预算仍需校验。
    AGENT_EVENT = "agent_event"


# Goal 的触发描述；参数和启用状态是显式数据，不拥有自动执行权。
@dataclass(frozen=True)
class Trigger:
    # trigger_id：显式触发描述身份，不是可执行机会。
    trigger_id: str
    # goal_id：长期意图身份；跨会话/Run 保持稳定，不授予执行权限。
    goal_id: str
    # kind：当前合同的对象/记忆用途分类；需与所属枚举解释。
    kind: TriggerKind
    # spec：触发/注册的显式参数合同；不隐式增加权限。
    spec: dict[str, Any]
    # enabled：明确启用开关；只作用于未来目录/准入。
    enabled: bool = True
