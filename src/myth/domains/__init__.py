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

__all__ = [
    "CoordinationStrategy",
    "RouteTarget",
    "StrategyRegistry",
    "StrategySpec",
    "StrategyState",
    "Trigger",
    "TriggerKind",
    "default_strategies",
]
