"""Coordination strategies are composable policies, not architecture layers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class RouteTarget(StrEnum):
    MODEL = "model"
    TOOL = "tool"
    WORKFLOW = "workflow"
    AGENT = "agent"
    REMOTE_AGENT = "remote_agent"
    HUMAN = "human"


class StrategyState(StrEnum):
    EXISTS = "exists"
    CONNECTED = "connected"
    USABLE = "usable"
    HARDENED = "hardened"
    PLANNED = "planned"


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    label: str
    state: StrategyState
    responsibility: str


class CoordinationStrategy(Protocol):
    """Choose future work without owning execution authority."""

    strategy_id: str

    def next_work(self, context: dict[str, Any]) -> dict[str, Any] | None: ...


class StrategyRegistry:
    def __init__(self, specs: tuple[StrategySpec, ...] = ()) -> None:
        self._specs: dict[str, StrategySpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: StrategySpec) -> None:
        if not spec.strategy_id or spec.strategy_id in self._specs:
            raise ValueError(f"duplicate/empty strategy: {spec.strategy_id}")
        self._specs[spec.strategy_id] = spec

    def list(self) -> tuple[StrategySpec, ...]:
        return tuple(sorted(self._specs.values(), key=lambda item: item.strategy_id))

    def get(self, strategy_id: str) -> StrategySpec:
        return self._specs[strategy_id]


def default_strategies() -> StrategyRegistry:
    return StrategyRegistry((
        StrategySpec(
            "intent_pick",
            "Intent Pick",
            StrategyState.CONNECTED,
            "Conservative cascade routes strict arithmetic locally and explicit/strong admitted knowledge through local retrieval; unmatched input falls back to the Agent Loop.",
        ),
        StrategySpec(
            "information_resolution",
            "Information Resolution",
            StrategyState.CONNECTED,
            "Turn admission resolves a durable active rule/fixed policy into L0/L1/L2 and freezes the policy identity; explicit promotion/rollback affects future Turns only.",
        ),
        StrategySpec(
            "information_gain",
            "Information Gain",
            StrategyState.CONNECTED,
            "Paired fixed-case eval plus cross-case calibration can estimate observed quality delta and explicit-cost gain-per-cost; evidence gates policy release but never auto-promotes.",
        ),
        StrategySpec(
            "direct",
            "Direct",
            StrategyState.USABLE,
            "Answer or complete without delegating through a workflow.",
        ),
        StrategySpec(
            "agent_loop",
            "Agent Loop",
            StrategyState.USABLE,
            "Model chooses the next StepDecision and may repeat tool/model steps.",
        ),
        StrategySpec(
            "workflow",
            "Workflow",
            StrategyState.CONNECTED,
            "Validated dependency graph exists; durable workflow execution is not complete.",
        ),
        StrategySpec(
            "routing",
            "Routing",
            StrategyState.EXISTS,
            "Choose a model/tool/workflow/agent/human target without becoming a mandatory layer.",
        ),
        StrategySpec(
            "parallel",
            "Parallel",
            StrategyState.EXISTS,
            "Coordinate independent work in parallel under shared budgets.",
        ),
        StrategySpec(
            "multi_agent",
            "Multi-Agent",
            StrategyState.EXISTS,
            "Delegate bounded child Runs to role-scoped agents.",
        ),
        StrategySpec(
            "managed_agent",
            "Managed Agent",
            StrategyState.EXISTS,
            "Delegate coordination to a remote managed Agent behind an AgentPort.",
        ),
        StrategySpec(
            "personal_agent",
            "Personal Agent",
            StrategyState.EXISTS,
            "Use long-lived Goals and Triggers to start Runs beyond a chat turn.",
        ),
    ))
