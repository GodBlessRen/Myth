"""Architecture metadata for Myth's composable runtime.

These are descriptive maturity records, not mandatory execution layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Maturity(StrEnum):
    EXISTS = "exists"
    CONNECTED = "connected"
    USABLE = "usable"
    HARDENED = "hardened"
    PLANNED = "planned"


@dataclass(frozen=True)
class ArchitectureItem:
    item_id: str
    label: str
    kind: str
    maturity: Maturity
    responsibility: str
    depends_on: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.item_id,
            "label": self.label,
            "kind": self.kind,
            "maturity": self.maturity.value,
            "responsibility": self.responsibility,
            "depends_on": list(self.depends_on),
        }


# Backward-compatible names for older imports.  New code should use
# Maturity/ArchitectureItem and should not model Myth as a strict layer stack.
LayerState = Maturity
PlatformLayer = ArchitectureItem
