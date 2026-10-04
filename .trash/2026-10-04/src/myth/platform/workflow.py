"""工作流依赖与就绪判定的纯函数。
校验节点、引用和有向无环性后按完成集合推导下一批步骤；不负责数据库、调度线程或执行副作用。"""

from __future__ import annotations

from dataclasses import dataclass


# 工作流原子节点描述；depends_on 只表达先决关系，不意味着依赖已成功。
@dataclass(frozen=True)
class WorkflowStep:
    # step_id：工作流节点身份；在同图内必须唯一。
    step_id: str
    # capability_id：明确本地能力身份；仍须核对版本、状态和准入范围。
    capability_id: str
    # depends_on：显式前置依赖身份；不是已完成证明。
    depends_on: tuple[str, ...] = ()


# 固定节点和依赖的不可变工作流合同；图校验与真实执行分别处理。
@dataclass(frozen=True)
class WorkflowSpec:
    # workflow_id：固定工作流合同身份；不拥有执行状态。
    workflow_id: str
    # steps：固定工作流节点序列；实际完成集合另行管理。
    steps: tuple[WorkflowStep, ...]


# 校验唯一节点、所有依赖存在和无环；纯校验不写步骤完成状态。
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

    # 用 visiting/visited 深度优先检测回边；正在访问集合出现同节点即循环。
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


# 先验证图，再返回所有依赖已完成且自身未完成节点；这只是调度提案。
def ready_steps(spec: WorkflowSpec, completed: set[str]) -> tuple[WorkflowStep, ...]:
    validate_workflow(spec)
    return tuple(
        step
        for step in spec.steps
        if step.step_id not in completed and set(step.depends_on) <= completed
    )
