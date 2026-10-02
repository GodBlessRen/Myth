"""Workflow skeleton: validate dependencies before scheduling any external work."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    capability_id: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowSpec:
    workflow_id: str
    steps: tuple[WorkflowStep, ...]


def validate_workflow(spec: WorkflowSpec) -> None:
    ids = [step.step_id for step in spec.steps]
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        raise ValueError("workflow step ids must be non-empty and unique")
    known = set(ids)
    for step in spec.steps:
        if not set(step.depends_on) <= known:
            raise ValueError(f"unknown workflow dependency in {step.step_id}")

    visiting: set[str] = set()
    visited: set[str] = set()
    deps = {step.step_id: step.depends_on for step in spec.steps}

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise ValueError("workflow contains a cycle")
        if step_id in visited:
            return
        visiting.add(step_id)
        for parent in deps[step_id]:
            visit(parent)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in ids:
        visit(step_id)


def ready_steps(spec: WorkflowSpec, completed: set[str]) -> tuple[WorkflowStep, ...]:
    validate_workflow(spec)
    return tuple(
        step for step in spec.steps
        if step.step_id not in completed and set(step.depends_on) <= completed
    )
