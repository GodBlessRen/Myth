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

# __all__：公开导出名单；兼容别名只有在确认外部迁移完成后才删除。
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
