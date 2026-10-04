"""最小核心合同的公开导出。
包导出本身不启动业务工作；具体状态归属、I/O 和恢复合同见被导出模块。"""

from .primitives import Goal, GoalState

# __all__：当前公开入口；新增入口必须有实际调用方。
__all__ = ["Goal", "GoalState"]
