"""Orthogonal Myth domains.

Domains are peers around the durable core, not mandatory sequential layers.
"""

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
