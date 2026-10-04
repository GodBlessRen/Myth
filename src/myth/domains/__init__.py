"""同级纯领域合同包入口。
包导出本身不启动业务工作；具体状态归属、I/O 和恢复合同见被导出模块。"""

from .coordination import (
    CoordinationStrategy,
    RouteTarget,
    StrategyRegistry,
    StrategySpec,
    StrategyState,
    default_strategies,
)
from .personal import Trigger, TriggerKind
from .information import (
    InformationDelta,
    InformationGain,
    InformationResolution,
    InformationView,
    IntentPick,
    IntentRoute,
)
from .intent import IntentPicker

# __all__：当前公开入口；新增入口必须有实际调用方。
__all__ = [
    "CoordinationStrategy",
    "RouteTarget",
    "StrategyRegistry",
    "StrategySpec",
    "StrategyState",
    "Trigger",
    "TriggerKind",
    "InformationDelta",
    "InformationGain",
    "InformationResolution",
    "InformationView",
    "IntentPick",
    "IntentRoute",
    "IntentPicker",
    "default_strategies",
]
