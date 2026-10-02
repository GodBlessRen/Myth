"""Retrieval/RAG route registry.  Backends may exist before they are ready."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RetrievalMode(StrEnum):
    KEYWORD = "keyword"
    VECTOR = "vector"
    HYBRID = "hybrid"
    GRAPH = "graph"


@dataclass(frozen=True)
class RetrievalBackend:
    backend_id: str
    mode: RetrievalMode
    ready: bool
    provenance: bool = True


class RetrievalRouter:
    def __init__(self, backends: tuple[RetrievalBackend, ...]) -> None:
        self.backends = backends

    def available(self) -> tuple[RetrievalBackend, ...]:
        return tuple(item for item in self.backends if item.ready)

    def choose(self, *, semantic: bool = False, relational: bool = False) -> RetrievalBackend:
        ready = self.available()
        preferences = (
            (RetrievalMode.GRAPH, RetrievalMode.HYBRID, RetrievalMode.KEYWORD)
            if relational
            else (RetrievalMode.HYBRID, RetrievalMode.VECTOR, RetrievalMode.KEYWORD)
            if semantic
            else (RetrievalMode.KEYWORD, RetrievalMode.HYBRID)
        )
        for mode in preferences:
            for backend in ready:
                if backend.mode is mode:
                    return backend
        raise LookupError("no retrieval backend is ready")
