"""Typed Memory skeleton: facts are versioned entries, not hidden prompt mutation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


class MemoryKind(StrEnum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    kind: MemoryKind
    text: str
    source_ref: str
    revision: int = 1
    active: bool = True


class MemoryCatalog:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    def put(self, record: MemoryRecord) -> None:
        previous = self._records.get(record.memory_id)
        if previous and record.revision <= previous.revision:
            raise ValueError("memory revision must increase")
        self._records[record.memory_id] = record

    def revoke(self, memory_id: str, *, revision: int) -> None:
        current = self._records[memory_id]
        self.put(MemoryRecord(memory_id, current.kind, current.text, current.source_ref, revision, False))

    def search(self, query: str, *, kinds: set[MemoryKind] | None = None, limit: int = 8) -> list[MemoryRecord]:
        terms = set(re.findall(r"[\w\u4e00-\u9fff]+", query.lower()))
        scored: list[tuple[int, MemoryRecord]] = []
        for record in self._records.values():
            if not record.active or (kinds and record.kind not in kinds):
                continue
            text_terms = set(re.findall(r"[\w\u4e00-\u9fff]+", record.text.lower()))
            score = len(terms & text_terms)
            if not terms or score:
                scored.append((score, record))
        scored.sort(key=lambda pair: (-pair[0], pair[1].memory_id))
        return [record for _, record in scored[:limit]]
