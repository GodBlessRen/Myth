"""Pure Control Plane state machine.

This does not persist commands yet.  It establishes the command vocabulary and
transition semantics that the durable repository will adopt.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any


class ControlCommand(StrEnum):
    STEER = "steer"
    PAUSE = "pause"
    RESUME = "resume"
    ABORT = "abort"
    SWITCH_MODEL = "switch_model"
    SWITCH_THINKING = "switch_thinking"
    COMPACT = "compact"


@dataclass(frozen=True)
class ControlSnapshot:
    revision: int = 1
    paused: bool = False
    aborted: bool = False
    model: str | None = None
    thinking: str | bool | None = None
    steering_note: str | None = None
    compact_requested: bool = False


class ControlPlane:
    """Apply one explicit command without performing model/tool I/O."""

    def apply(self, state: ControlSnapshot, command: ControlCommand, payload: Any = None) -> ControlSnapshot:
        if state.aborted:
            raise ValueError("aborted control state is terminal")

        update: dict[str, Any] = {"revision": state.revision + 1}
        if command is ControlCommand.PAUSE:
            if state.paused:
                raise ValueError("run is already paused")
            update["paused"] = True
        elif command is ControlCommand.RESUME:
            if not state.paused:
                raise ValueError("run is not paused")
            update["paused"] = False
        elif command is ControlCommand.ABORT:
            update["aborted"] = True
            update["paused"] = False
        elif command is ControlCommand.SWITCH_MODEL:
            value = str(payload or "").strip()
            if not value:
                raise ValueError("model must be non-empty")
            update["model"] = value
        elif command is ControlCommand.SWITCH_THINKING:
            if payload is None:
                update["thinking"] = None
            elif isinstance(payload, bool):
                update["thinking"] = payload
            else:
                value = str(payload).strip().lower()
                if value in {"true", "on"}:
                    update["thinking"] = True
                elif value in {"false", "off"}:
                    update["thinking"] = False
                elif value in {"low", "medium", "high"}:
                    update["thinking"] = value
                elif not value or value == "default":
                    update["thinking"] = None
                else:
                    raise ValueError("thinking must be default/on/off/low/medium/high")
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
