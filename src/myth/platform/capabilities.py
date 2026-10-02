"""Capability Registry: discovery is separate from execution authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class CapabilityState(StrEnum):
    EXECUTABLE = "executable"
    WIRED = "wired"
    PLANNED = "planned"


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    version: str
    description: str
    risk: str
    state: CapabilityState
    family: str


class CapabilityRegistry:
    def __init__(self, specs: Iterable[CapabilitySpec] = ()) -> None:
        self._specs: dict[str, CapabilitySpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: CapabilitySpec) -> None:
        if not spec.capability_id or spec.capability_id in self._specs:
            raise ValueError(f"duplicate/empty capability: {spec.capability_id}")
        self._specs[spec.capability_id] = spec

    def get(self, capability_id: str) -> CapabilitySpec:
        try:
            return self._specs[capability_id]
        except KeyError as exc:
            raise KeyError(f"unknown capability: {capability_id}") from exc

    def list(self, *, executable_only: bool = False) -> list[CapabilitySpec]:
        values = sorted(self._specs.values(), key=lambda item: (item.family, item.capability_id))
        return [item for item in values if item.state is CapabilityState.EXECUTABLE] if executable_only else values

    def executable_ids(self) -> tuple[str, ...]:
        return tuple(item.capability_id for item in self.list(executable_only=True))


def default_capabilities() -> CapabilityRegistry:
    executable = [
        ("knowledge.search", "knowledge", "Search local indexed text with source references.", "read"),
        ("knowledge.read", "knowledge", "Expand one admitted knowledge document to paginated L2 evidence.", "read"),
        ("knowledge.resolve", "knowledge", "Project one admitted knowledge source at L0/L1/L2 under a fixed digest.", "read"),
        ("project.list", "file", "List an explicitly associated project directory.", "read"),
        ("project.read", "file", "Read UTF-8 project content inside the admitted root.", "read"),
        ("artifact.write", "file", "Write a managed output artifact without overwriting source files.", "write"),
        ("project.patch_exact", "file", "Create an exact-patched managed copy of a project file.", "write"),
        ("math.calculate", "compute", "Evaluate bounded arithmetic only.", "compute"),
        ("file.read", "file", "Read fixed managed bytes in exact verification mode.", "read"),
        ("file.patch_exact", "file", "Exact replacement in the durable managed workspace.", "write"),
        ("project.search", "file", "Search admitted project text without widening file scope.", "read"),
        ("diff.preview", "file", "Render a bounded unified diff without writing the source file.", "read"),
        ("git.status", "git", "Inspect repository status through fixed read-only argv.", "read"),
        ("git.diff", "git", "Inspect repository diff through fixed read-only argv.", "read"),
    ]
    planned = [
        ("test.run", "execution", "Run an admitted test command in a controlled executor.", "execute"),
        ("shell.exec", "execution", "Execute an admitted command profile, never arbitrary by default.", "execute"),
        ("python.run", "execution", "Execute bounded Python in a controlled environment.", "execute"),
        ("web.fetch", "web", "Fetch an admitted URL with provenance.", "network"),
        ("browser.navigate", "web", "Drive an authenticated browser adapter.", "network"),
    ]
    specs = [
        CapabilitySpec(cid, "v1", desc, risk, CapabilityState.EXECUTABLE, family)
        for cid, family, desc, risk in executable
    ]
    specs += [
        CapabilitySpec(cid, "v0", desc, risk, CapabilityState.PLANNED, family)
        for cid, family, desc, risk in planned
    ]
    return CapabilityRegistry(specs)
