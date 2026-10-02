"""SubAgent role registry with explicit budget slicing; no autonomous spawn yet."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubAgentSpec:
    role_id: str
    instruction: str
    capability_allowlist: tuple[str, ...]
    max_steps: int = 6
    budget_fraction: float = 0.25

    def __post_init__(self) -> None:
        if not self.role_id or self.max_steps <= 0:
            raise ValueError("invalid sub-agent spec")
        if not (0 < self.budget_fraction <= 1):
            raise ValueError("budget_fraction must be in (0, 1]")


class SubAgentRegistry:
    def __init__(self) -> None:
        self._roles: dict[str, SubAgentSpec] = {}

    def register(self, spec: SubAgentSpec) -> None:
        if spec.role_id in self._roles:
            raise ValueError(f"duplicate sub-agent role: {spec.role_id}")
        self._roles[spec.role_id] = spec

    def get(self, role_id: str) -> SubAgentSpec:
        return self._roles[role_id]

    def child_budget(self, role_id: str, parent_budget: dict[str, int]) -> dict[str, int]:
        fraction = self.get(role_id).budget_fraction
        return {meter: max(0, int(amount * fraction)) for meter, amount in parent_budget.items()}
