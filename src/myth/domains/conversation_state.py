"""Conversation Turn 的纯状态迁移合同。

这里集中“哪些持久状态可以变成哪些状态”；不拥有数据库、Driver、Provider 或 UI。
状态写入仍由 SqliteWorkspaceRepository 在事务内完成，因此 FSM 只约束语义，不取代状态所有权。
"""

from __future__ import annotations

from ..domain import InvalidTransition


# ACTIVE_TURN_STATUSES：仍占有 Session 的持久状态；新 Turn 不能绕过这些未完成工作。
ACTIVE_TURN_STATUSES = frozenset(
    {"RUNNING", "INTERRUPTED", "UNKNOWN", "WAITING_USER", "PAUSED"}
)
# DRIVABLE_TURN_STATUSES：ConversationAgent 可进入恢复/驱动流程的状态；PAUSED/WAITING_USER 需外部动作。
DRIVABLE_TURN_STATUSES = frozenset({"RUNNING", "INTERRUPTED", "UNKNOWN"})
# EXECUTOR_TURN_STATUSES：后台执行器可主动接管的状态；UNKNOWN 必须先显式 reconcile，不能自动派发。
EXECUTOR_TURN_STATUSES = frozenset({"RUNNING", "INTERRUPTED"})
# PAUSABLE_TURN_STATUSES：安全点允许暂停未来规划的状态；不撤销已经签发的 Ticket。
PAUSABLE_TURN_STATUSES = frozenset({"RUNNING", "INTERRUPTED", "UNKNOWN"})
# TERMINAL_TURN_STATUSES：Conversation 不再接受未来规划；晚到执行事实仍可由底层收据记录。
TERMINAL_TURN_STATUSES = frozenset(
    {"COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"}
)


# _TRANSITIONS：当前产品已存在的合法迁移。相同状态允许幂等保存，但终态不能重新打开。
_TRANSITIONS = {
    "RUNNING": frozenset({
        "RUNNING", "INTERRUPTED", "UNKNOWN", "WAITING_USER", "PAUSED",
        "COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED",
    }),
    "INTERRUPTED": frozenset({
        "RUNNING", "INTERRUPTED", "UNKNOWN", "PAUSED",
        "FAILED", "CANCELLED", "BUDGET_EXHAUSTED",
    }),
    "UNKNOWN": frozenset({
        "RUNNING", "INTERRUPTED", "UNKNOWN", "PAUSED",
        "FAILED", "CANCELLED", "BUDGET_EXHAUSTED",
    }),
    "WAITING_USER": frozenset({
        "RUNNING", "WAITING_USER", "UNKNOWN",
        "FAILED", "CANCELLED", "BUDGET_EXHAUSTED",
    }),
    "PAUSED": frozenset({
        "RUNNING", "PAUSED", "UNKNOWN",
        "FAILED", "CANCELLED", "BUDGET_EXHAUSTED",
    }),
    "COMPLETED": frozenset({"COMPLETED"}),
    "FAILED": frozenset({"FAILED"}),
    "CANCELLED": frozenset({"CANCELLED"}),
    "BUDGET_EXHAUSTED": frozenset({"BUDGET_EXHAUSTED"}),
}


# can_transition：只判断状态语义；调用方不能用 True 替代数据库事务或 Ticket/Receipt 核对。
def can_transition(current: str, target: str) -> bool:
    return target in _TRANSITIONS.get(str(current), frozenset())


# require_transition：在写事务内调用；非法迁移显式失败，避免各调用点自行维护状态集合。
def require_transition(current: str, target: str) -> str:
    current, target = str(current), str(target)
    if not can_transition(current, target):
        raise InvalidTransition(
            f"conversation turn cannot transition from {current} to {target}"
        )
    return target


# is_active：Session 占用语义的唯一判定入口；它不表示当前可自动执行。
def is_active(status: str) -> bool:
    return str(status) in ACTIVE_TURN_STATUSES


# is_drivable：ConversationAgent 是否可进入 recover/reopen；具体新效果仍需 Runtime 准入。
def is_drivable(status: str) -> bool:
    return str(status) in DRIVABLE_TURN_STATUSES


# is_executor_candidate：后台 worker 是否可接管；UNKNOWN 不在此集合，防止把不明效果当未开始。
def is_executor_candidate(status: str) -> bool:
    return str(status) in EXECUTOR_TURN_STATUSES


# is_pausable：控制安全点是否允许暂停未来规划；WAITING_USER 已经自然停止，不需要改写为 PAUSED。
def is_pausable(status: str) -> bool:
    return str(status) in PAUSABLE_TURN_STATUSES


# __all__：只暴露状态合同和 named guards；不暴露内部迁移表供调用方自行修改。
__all__ = [
    "ACTIVE_TURN_STATUSES",
    "DRIVABLE_TURN_STATUSES",
    "EXECUTOR_TURN_STATUSES",
    "TERMINAL_TURN_STATUSES",
    "can_transition",
    "require_transition",
    "is_active",
    "is_drivable",
    "is_executor_candidate",
    "is_pausable",
]
