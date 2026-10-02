"""Personal-Agent contracts: explicit Goals/Triggers, not implicit Memory authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class TriggerKind(StrEnum):
    USER = "user"
    TIMER = "timer"
    SCHEDULE = "schedule"
    EVENT = "event"
    WEBHOOK = "webhook"
    EMAIL = "email"
    FILE_CHANGE = "file_change"
    AGENT_EVENT = "agent_event"


@dataclass(frozen=True)
class Trigger:
    trigger_id: str
    goal_id: str
    kind: TriggerKind
    spec: dict[str, Any]
    enabled: bool = True
