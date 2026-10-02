"""Pure Control domain state machine.

Control changes future scheduling at safe points.  It never performs model/tool
I/O and never erases an already-issued Ticket or late Receipt.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any


class ControlCommand(StrEnum):
    STEER = "steer"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    # Backward compatibility for v0.8 persisted/API vocabulary.
    ABORT = "abort"
    SWITCH_MODEL = "switch_model"
    SWITCH_THINKING = "switch_thinking"
    COMPACT = "compact"


@dataclass(frozen=True)
class ControlSnapshot:
    revision: int = 1
    paused: bool = False
    stopped: bool = False
    model: str | None = None
    thinking: str | bool | None = None
    steering_note: str | None = None
    compact_requested: bool = False

    @property
    def aborted(self) -> bool:
        """Compatibility alias for old callers."""

        return self.stopped


class ControlService:
    """Apply one explicit control command without performing external I/O."""

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
        elif command in {ControlCommand.STOP, ControlCommand.ABORT}:
            update["stopped"] = True
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


# Compatibility alias.  New docs/code use "Control" rather than "Control Plane".
ControlPlane = ControlService

__all__ = [
    "ControlCommand",
    "ControlSnapshot",
    "ControlService",
    "ControlPlane",
]
