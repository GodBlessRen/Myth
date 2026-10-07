"""受信本机工具 Hook 的合同、注册与同步派发。
前置 Hook 只能继续或拒绝；观察 Hook 不能覆写工具参数、收据或 UNKNOWN。回调在事务外运行。"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
import re
from threading import RLock
from time import monotonic
from types import MappingProxyType
from typing import Callable, Mapping


# PHASES：执行器唯一支持的阶段；工具恢复不再次派发这些回调。
PHASES = frozenset({"before_tool", "after_tool", "on_tool_error"})
# HOOK_ID：事件只记录受限身份，不记录任意回调说明或异常正文。
HOOK_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
# TOOL_PATTERN：只匹配 Runtime 的能力名；不把文件路径或 MCP 命令当作匹配输入。
TOOL_PATTERN = re.compile(r"[a-z0-9_.*?-]{1,100}\Z")


def readonly_json(value):
    """递归复制并冻结 JSON 数据；回调既得不到原引用，也不能修改嵌套参数/结果。"""
    if isinstance(value, dict):
        return MappingProxyType({key: readonly_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(readonly_json(item) for item in value)
    if value is None or type(value) in {str, int, float, bool}:
        return value
    raise ValueError("tool hook context requires JSON data")


@dataclass(frozen=True)
class ToolHookContext:
    """单次阶段的只读投影；不暴露 Runtime、仓储、Provider 或异常对象。"""

    # run_id/decision_id：固定调用身份；没有 Ticket 的拒绝也可追溯。
    run_id: str
    decision_id: str
    # capability_id/phase：匹配目标及当前阶段，不能由回调更改。
    capability_id: str
    phase: str
    # arguments/result：递归冻结的独立快照；观察不是执行授权。
    # arguments：工具参数的递归只读副本；回调不能修改原调用。
    arguments: Mapping
    # result：仅观察阶段提供的递归只读结果；前置阶段固定为空。
    result: Mapping | None = None
    # operation_state：当前持久状态，空值表示尚无工具 Ticket。
    # operation_state：当前 Ticket/收据状态；无 Ticket 时为空，不能据此补签授权。
    operation_state: str | None = None
    # error_type：稳定类别标识，不包含可能携带凭据的异常正文。
    # error_type：稳定错误类别；不保存可能含凭据的异常正文。
    error_type: str | None = None


@dataclass(frozen=True)
class ToolHookDecision:
    """前置回调的唯一有效返回合同；None 也表示继续既有准入流程。"""

    # denied：仅能缩小执行范围，False 不签发授权。
    # denied：只允许前置 Hook 缩小执行范围；False 不代表授权成功。
    denied: bool = False
    # reason_code：受限机器码，禁止携带参数、凭据或任意说明。
    # reason_code：稳定机器码，供审计/恢复判断；禁止塞入自由文本。
    reason_code: str = "policy_denied"

    def __post_init__(self):
        """在回调返回前固定机器码与布尔形状；无效返回按前置失败处理。"""
        if type(self.denied) is not bool or not isinstance(self.reason_code, str) or not HOOK_ID.fullmatch(self.reason_code):
            raise ValueError("invalid tool hook decision")


@dataclass(frozen=True)
class ToolHook:
    """可注册回调的稳定描述；优先级较小者先运行，同级按身份排序。"""

    # hook_id/phase/callback：唯一身份、单一阶段及受信同步回调。
    hook_id: str
    phase: str
    callback: Callable[[ToolHookContext], ToolHookDecision | None]
    # tools：能力名或 glob；不会扩大 Capability/项目/预算权限。
    tools: tuple[str, ...] = ("*",)
    # priority/enabled：顺序和开关；注册描述冻结，替换须先注销。
    priority: int = 0
    # enabled：仅控制当前注册项是否参与未来快照；不影响已冻结调用。
    enabled: bool = True

    def __post_init__(self):
        """限制注册数量以外的单项输入；目录中不会保存可变匹配列表。"""
        if not isinstance(self.hook_id, str) or not HOOK_ID.fullmatch(self.hook_id) or not isinstance(self.phase, str) or self.phase not in PHASES or not callable(self.callback):
            raise ValueError("invalid tool hook registration")
        if not isinstance(self.tools, (tuple, list)):
            raise ValueError("tool hook patterns must be a sequence")
        patterns = tuple(self.tools)
        if not 1 <= len(patterns) <= 16 or any(not isinstance(item, str) or not TOOL_PATTERN.fullmatch(item) for item in patterns):
            raise ValueError("tool hook requires bounded capability patterns")
        if type(self.priority) is not int or not -1000 <= self.priority <= 1000 or type(self.enabled) is not bool:
            raise ValueError("invalid tool hook priority or switch")
        object.__setattr__(self, "tools", patterns)

    def descriptor(self) -> dict:
        """公开不含回调或业务数据的目录；配置目录不证明 Hook 已实际运行。"""
        return {"hook_id": self.hook_id, "phase": self.phase, "tools": list(self.tools),
                "priority": self.priority, "enabled": self.enabled}


class ToolHookDenied(PermissionError):
    """Ticket 前的已知策略拒绝；由 Conversation 作为 Observation 消费。"""

    def __init__(self, hook_id: str, code: str, reason_code: str = "policy_denied"):
        """保存稳定拒绝分类；异常消息只由受限身份和机器码组成。"""
        # code/reason_code：由管线固定的错误分类，异常正文不包含回调输出。
        self.code, self.reason_code = code, reason_code
        super().__init__(f"tool hook denied: {hook_id}; {code}; {reason_code}")


class ToolHookRegistry:
    """装配根持有的注册表；每次工具调用取得一份固定阶段计划。"""

    def __init__(self):
        """创建空受信 Hook 目录；注册元数据与回调执行严格分离。"""
        # _hooks/_lock：只保护注册元数据；执行回调时不持锁，也不持数据库事务。
        # _hooks：按稳定身份保存受信回调描述；模型没有注册入口。
        self._hooks: dict[str, ToolHook] = {}
        # _lock：仅保护目录快照/增删，绝不包住用户回调。
        self._lock = RLock()

    def register(self, hook: ToolHook) -> None:
        """登记真实回调；重复身份拒绝，最多 32 项，模型没有此入口。"""
        if not isinstance(hook, ToolHook):
            raise ValueError("registration requires a ToolHook")
        with self._lock:
            if hook.hook_id in self._hooks or len(self._hooks) >= 32:
                raise ValueError("duplicate tool hook or registry full")
            self._hooks[hook.hook_id] = hook

    def unregister(self, hook_id: str) -> None:
        """只影响未来调用；已经取得快照的调用完成原阶段计划。"""
        with self._lock:
            self._hooks.pop(hook_id, None)

    def snapshot(self) -> tuple[ToolHook, ...]:
        """取得稳定顺序；具体文件适配器可合入操作者的声明式规则。"""
        with self._lock:
            return tuple(sorted(self._hooks.values(), key=lambda item: (item.priority, item.hook_id)))

    def descriptors(self) -> list[dict]:
        """只读目录入口，供扩展 API 与本机诊断使用。"""
        return [hook.descriptor() for hook in self.snapshot()]


def dispatch_tool_hooks(hooks, context: ToolHookContext, record: Callable[[dict], None]) -> None:
    """按冻结计划串行调用；前置失败关闭，观察失败隔离，原异常由执行器继续抛出。"""
    for hook in hooks:
        if not hook.enabled or hook.phase != context.phase or not any(fnmatchcase(context.capability_id, pattern) for pattern in hook.tools):
            continue
        started = monotonic()
        status, reason_code = "passed", None
        try:
            returned = hook.callback(context)
            if context.phase == "before_tool":
                if returned is not None and not isinstance(returned, ToolHookDecision):
                    raise ValueError("invalid before_tool return")
                if returned is not None and returned.denied:
                    status, reason_code = "denied", returned.reason_code
            elif returned is not None:
                # 观察回调没有结果替换权；返回值无效也只影响该 Hook 的状态。
                raise ValueError("observation hook must return None")
        except Exception:
            # 不把原始异常正文/堆栈写入事件；回调报错不改变底层工具事实。
            status, reason_code = "failed", "callback_failed"
        trace = {"hook_id": hook.hook_id, "phase": context.phase, "status": status,
                 "reason_code": reason_code, "duration_ms": max(0, int((monotonic() - started) * 1000)),
                 "operation_state": context.operation_state, "error_type": context.error_type}
        try:
            record(trace)
        except Exception:
            if context.phase == "before_tool":
                raise ToolHookDenied(hook.hook_id, "tool_hook_audit_failed", "audit_unavailable") from None
            # 已结算效果与原 UNKNOWN 不能因观察事件写入失败而被覆写或重放。
        if context.phase == "before_tool" and status != "passed":
            code = "tool_hook_denied" if status == "denied" else "tool_hook_failed"
            raise ToolHookDenied(hook.hook_id, code, reason_code) from None
