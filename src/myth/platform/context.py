"""Deterministic Context Compiler skeleton with provenance and byte budget."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextItem:
    source_ref: str
    content: str
    priority: int = 0
    required: bool = False


@dataclass(frozen=True)
class ContextFrame:
    items: tuple[ContextItem, ...]
    dropped: tuple[str, ...]
    bytes_used: int
    max_bytes: int


class ContextCompiler:
    def compile(self, items: list[ContextItem], *, max_bytes: int) -> ContextFrame:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        chosen: list[ContextItem] = []
        dropped: list[str] = []
        used = 0
        ordered = sorted(enumerate(items), key=lambda pair: (not pair[1].required, -pair[1].priority, pair[0]))
        for _, item in ordered:
            size = len(item.content.encode("utf-8"))
            if item.required and used + size > max_bytes:
                raise ValueError(f"required context exceeds budget: {item.source_ref}")
            if used + size <= max_bytes:
                chosen.append(item)
                used += size
            else:
                dropped.append(item.source_ref)
        return ContextFrame(tuple(chosen), tuple(dropped), used, max_bytes)
