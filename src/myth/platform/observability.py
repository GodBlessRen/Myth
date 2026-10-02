"""Observability projections are derived from facts; they never own Runtime truth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TraceEvent:
    sequence: int
    layer: str
    kind: str
    payload: dict[str, Any]


class TraceProjection:
    def summarize(self, events: list[TraceEvent]) -> dict[str, Any]:
        by_layer: dict[str, int] = {}
        unknown = 0
        for event in events:
            by_layer[event.layer] = by_layer.get(event.layer, 0) + 1
            if "unknown" in event.kind.lower():
                unknown += 1
        return {
            "events": len(events),
            "by_layer": dict(sorted(by_layer.items())),
            "unknown_events": unknown,
            "last_sequence": max((event.sequence for event in events), default=0),
        }
