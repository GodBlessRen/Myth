"""控制命令的纯状态转换规则。
修改未来规划与安全点状态，不撤销已发出的外部效果；持久命令序列与对话投影由 control_store 所有。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from ..model_capabilities import normalize_thinking


# 用户显式控制词汇；STOP 停止未来调度，已经发出的调用仍需结算。
class ControlCommand(StrEnum):
    # STEER：追加明确方向修正；不改已签发 Ticket 的范围。
    STEER = "steer"
    # PAUSE：明确请求暂停未来规划；已发出调用不会物理撤销。
    PAUSE = "pause"
    # RESUME：明确请求恢复已暂停工作；恢复仍先核对旧机会。
    RESUME = "resume"
    # STOP：明确终止未来派发；不能抹去晚到效果。
    STOP = "stop"
    # SWITCH_MODEL：明确修改未来模型调用选择；历史请求对象保持不变。
    SWITCH_MODEL = "switch_model"
    # SWITCH_THINKING：明确修改未来推理选项；不修改已发出调用。
    SWITCH_THINKING = "switch_thinking"
    # COMPACT：请求下一次实际模型上下文压缩；固定 revision 消费。
    COMPACT = "compact"


# 某 revision 的不可变控制投影；不包括外部效果是否成功。
@dataclass(frozen=True)
class ControlSnapshot:
    # revision：当前状态/记忆的单调版本；旧结果不能覆盖更新版本。
    revision: int = 1
    # paused：暂停未来规划的显式状态；已发出效果照常留收据。
    paused: bool = False
    # stopped：停止未来派发的显式状态；不代表物理撤销在途调用。
    stopped: bool = False
    # model：明确模型名称；请求创建/控制修订时固定。
    model: str | None = None
    # thinking：明确推理选项；None 代表供应商默认，不自动扩预算。
    thinking: str | bool | None = None
    # steering_note：用户明确方向修正；不修改既有 Ticket 或固定验收。
    steering_note: str | None = None
    # compact_requested：未来上下文压缩请求；按实际使用的 control revision 消费。
    compact_requested: bool = False



class ControlService:
    """纯控制状态机；只返回下一快照，持久提交和业务安全点归适配器。"""

    # 校验当前控制快照并返回 revision+1 的新快照；纯函数不写数据库或撤销外部效果。
    def apply(
        self,
        state: ControlSnapshot,
        command: ControlCommand,
        payload: Any = None,
    ) -> ControlSnapshot:
        if state.stopped:
            raise ValueError("stopped control state is terminal")

        update: dict[str, Any] = {"revision": state.revision + 1}
        if command is ControlCommand.PAUSE:
            if state.paused:
                raise ValueError("run is already paused")
            update["paused"] = True
        elif command is ControlCommand.RESUME:
            if not state.paused:
                raise ValueError("run is not paused")
            update["paused"] = False
        elif command is ControlCommand.STOP:
            update["stopped"] = True
            update["paused"] = False
        elif command is ControlCommand.SWITCH_MODEL:
            value = str(payload or "").strip()
            if not value:
                raise ValueError("model must be non-empty")
            update["model"] = value
        elif command is ControlCommand.SWITCH_THINKING:
            # Control 只保存用户显式 Provider 原生值；允许未来模型增加档位而无需修改控制状态机。
            update["thinking"] = normalize_thinking(payload)
        elif command is ControlCommand.STEER:
            value = str(payload or "").strip()
            if not value:
                raise ValueError("steering note must be non-empty")
            update["steering_note"] = value
        elif command is ControlCommand.COMPACT:
            update["compact_requested"] = True
        else:
            raise ValueError(f"unsupported control command: {command}")
        return replace(state, **update)


# __all__：当前公开入口；新增入口必须有实际调用方。
__all__ = [
    "ControlCommand",
    "ControlSnapshot",
    "ControlService",
]
