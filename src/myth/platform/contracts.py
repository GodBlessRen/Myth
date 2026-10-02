"""Shared product/runtime contracts for the breadth-first platform skeleton."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LayerState(StrEnum):
    USABLE = "usable"
    WIRED = "wired"
    PLANNED = "planned"


@dataclass(frozen=True)
class PlatformLayer:
    phase: str
    layer_id: str
    label: str
    state: LayerState
    responsibility: str
    depends_on: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "id": self.layer_id,
            "label": self.label,
            "state": self.state.value,
            "responsibility": self.responsibility,
            "depends_on": list(self.depends_on),
        }
