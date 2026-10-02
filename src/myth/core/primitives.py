"""Small stable primitives that survive changing Agent strategies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GoalState(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


@dataclass(frozen=True)
class Goal:
    """Long-lived user/system intent that may own many Runs over time."""

    goal_id: str
    title: str
    description: str
    state: GoalState = GoalState.ACTIVE
