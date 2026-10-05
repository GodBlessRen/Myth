"""能力描述和执行白名单的纯注册表。
发现、成熟度与可执行性分别判断；具体工具仍由执行适配器和 Ticket 校验，不能以注册条目冒充已执行结果。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


# 能力的可执行/已连接/计划状态；执行白名单只接受 executable。
class CapabilityState(StrEnum):
    # EXECUTABLE：能力已有实际执行路径；每次仍需 Ticket/范围校验。
    EXECUTABLE = "executable"
    # PLANNED：规划中的能力/后端；不会因登记而自动执行。
    PLANNED = "planned"


# 有版本、风险和家族的能力描述；具体实现另经准入和 Ticket 校验。
@dataclass(frozen=True)
class CapabilitySpec:
    # capability_id：明确本地能力身份；仍须核对版本、状态和准入范围。
    capability_id: str
    # version：固定合同/配置版本；历史比较必须保留版本身份。
    version: str
    # description：显式说明文本；不作为能力授权。
    description: str
    # risk：能力风险分类；只影响明确准入规则，不自行授权。
    risk: str
    # state：本合同的当前生命周期/成熟度；以所属枚举解释，不混用 Run 与 Goal 状态。
    state: CapabilityState
    # family：能力家族，用于目录组织和过滤。
    family: str


# 进程内能力白名单；拒绝重复身份，返回描述而不是执行器或收据。
class CapabilityRegistry:
    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
    def __init__(self, specs: Iterable[CapabilitySpec] = ()) -> None:
        # _specs：已登记能力/策略合同；重复身份拒绝，注册不产生 Ticket。
        self._specs: dict[str, CapabilitySpec] = {}
        for spec in specs:
            self.register(spec)

    # 按稳定身份登记显式合同；校验冲突以避免悄悄替换已存在定义。
    def register(self, spec: CapabilitySpec) -> None:
        if not spec.capability_id or spec.capability_id in self._specs:
            raise ValueError(f"duplicate/empty capability: {spec.capability_id}")
        self._specs[spec.capability_id] = spec

    # 按身份取得已登记数据；缺失身份显式失败，调用方不能据此捏造已存在对象。
    def get(self, capability_id: str) -> CapabilitySpec:
        try:
            return self._specs[capability_id]
        except KeyError as exc:
            raise KeyError(f"unknown capability: {capability_id}") from exc

    # 返回当前目录/仓储的可见条目；排序和过滤只生成投影，不授予执行权。
    def list(self, *, executable_only: bool = False) -> list[CapabilitySpec]:
        values = sorted(
            self._specs.values(), key=lambda item: (item.family, item.capability_id)
        )
        return (
            [item for item in values if item.state is CapabilityState.EXECUTABLE]
            if executable_only
            else values
        )

    # 从显式 executable 合同生成白名单；planned/wired 条目不进入可执行集合。
    def executable_ids(self) -> tuple[str, ...]:
        return tuple(item.capability_id for item in self.list(executable_only=True))


# 登记已接入工具及其效果合同；执行由适配器承担，test.run 仍需显式受信 profile。
def default_capabilities() -> CapabilityRegistry:
    executable = [
        (
            "knowledge.search",
            "knowledge",
            "Search local indexed text with source references.",
            "read",
        ),
        (
            "knowledge.resolve",
            "knowledge",
            "Project one admitted knowledge source at L0/L1/L2 under a fixed digest.",
            "read",
        ),
        (
            "memory.search",
            "memory",
            "Search visible long-term memories and return compact L0 index views.",
            "read",
        ),
        (
            "memory.timeline",
            "memory",
            "Navigate visible memories around one admitted anchor without changing source facts.",
            "read",
        ),
        (
            "memory.resolve",
            "memory",
            "Expand one visible memory at L0/L1/L2 while preserving memory identity and revision.",
            "read",
        ),
        (
            "project.list",
            "file",
            "List an explicitly associated project directory.",
            "read",
        ),
        (
            "project.read",
            "file",
            "Read UTF-8 project content inside the admitted root.",
            "read",
        ),
        (
            "observation.read",
            "evidence",
            "Recall an exact paginated field from a prior durable tool observation.",
            "read",
        ),
        (
            "artifact.write",
            "file",
            "Write a managed output artifact without overwriting source files.",
            "write",
        ),
        (
            "project.patch_exact",
            "file",
            "Create an exact-patched managed copy of a project file.",
            "write",
        ),
        (
            "test.run",
            "execution",
            "Run an explicitly trusted Python unittest profile; no arbitrary shell.",
            "execute",
        ),
        ("math.calculate", "compute", "Evaluate bounded arithmetic only.", "compute"),
        (
            "agent.delegate",
            "agent",
            "Run one bounded read-only isolated sub-agent and return a contracted result.",
            "compute",
        ),
        ("agent.evaluate", "coordination", "Record a parent assessment of a settled child result.", "compute"),
        (
            "tool.search",
            "tooling",
            "Search the executable conversation tool catalog without executing a tool.",
            "read",
        ),
        (
            "tool.describe",
            "tooling",
            "Describe one discovered conversation tool so it can be exposed on the next step.",
            "read",
        ),
        (
            "file.read",
            "file",
            "Read fixed managed bytes in exact verification mode.",
            "read",
        ),
        (
            "file.patch_exact",
            "file",
            "Exact replacement in the durable managed workspace.",
            "write",
        ),
        (
            "project.search",
            "file",
            "Search admitted project text without widening file scope.",
            "read",
        ),
        (
            "diff.preview",
            "file",
            "Render a bounded unified diff without writing the source file.",
            "read",
        ),
        (
            "git.status",
            "git",
            "Inspect repository status through fixed read-only argv.",
            "read",
        ),
        (
            "git.diff",
            "git",
            "Inspect repository diff through fixed read-only argv.",
            "read",
        ),
    ]
    specs = [
        CapabilitySpec(cid, "v1", desc, risk, CapabilityState.EXECUTABLE, family)
        for cid, family, desc, risk in executable
    ]
    return CapabilityRegistry(specs)


# 当前模型工具面中的能力可达性投影；注册、启用、暴露分开解释，任何一项都不等于已经执行。
@dataclass(frozen=True)
class CapabilityReachability:
    # capability_id：现有 Capability Registry 中的能力身份。
    capability_id: str
    # enabled：当前策略是否允许该能力出现在工具面。
    enabled: bool
    # available：Runtime 是否有 executable 实现。
    available: bool
    # exposed：本次模型请求是否实际看到了该能力。
    exposed: bool
    # reachable：前三项同时成立后的派生事实。
    reachable: bool
    # reason_code：供 Runtime Observatory 稳定解释不可达原因。
    reason_code: str

    # 转为只读观测投影；不改变 Capability/Ticket/权限事实。
    def as_dict(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "enabled": self.enabled,
            "available": self.available,
            "exposed": self.exposed,
            "reachable": self.reachable,
            "reason_code": self.reason_code,
        }


# 由现有 Capability Registry 和本次工具披露事实计算可达性；不另建“机制注册表”。
def capability_reachability(
    registry: CapabilityRegistry,
    capability_id: str,
    *,
    enabled: bool,
    exposed: bool,
) -> CapabilityReachability:
    try:
        spec = registry.get(capability_id)
    except KeyError:
        available = False
    else:
        available = spec.state is CapabilityState.EXECUTABLE
    if not enabled:
        reason = "disabled"
    elif not available:
        reason = "implementation_unavailable"
    elif not exposed:
        reason = "surface_not_exposed"
    else:
        reason = "reachable"
    return CapabilityReachability(
        capability_id=capability_id,
        enabled=enabled,
        available=available,
        exposed=exposed,
        reachable=enabled and available and exposed,
        reason_code=reason,
    )
