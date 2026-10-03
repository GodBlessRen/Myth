"""子 Agent 描述和预算分配的纯合同。
父预算给出硬上限，注册不产生远端调用；实际并行或远端执行能力尚需对应执行适配器。"""

from __future__ import annotations

from dataclasses import dataclass


# 显式子角色与预算比例合同；不包含自主启动实现。
@dataclass(frozen=True)
class SubAgentSpec:
    # role_id：子 Agent 角色身份；不代表已经启动子工作。
    role_id: str
    # instruction：角色的显式工作说明；不能覆盖父授权上限。
    instruction: str
    # capability_allowlist：角色明确允许能力集合；仍受父 Run 准入约束。
    capability_allowlist: tuple[str, ...]
    # max_steps：用例/角色步骤硬上限；单位为规划步骤。
    max_steps: int = 6
    # budget_fraction：从父额度分配的比例，范围 (0,1]；按 meter 向下取整。
    budget_fraction: float = 0.25

    # 在合同构造时校验输入边界；非法值提前拒绝，避免进入后续执行或比较。
    def __post_init__(self) -> None:
        if not self.role_id or self.max_steps <= 0:
            raise ValueError("invalid sub-agent spec")
        if not (0 < self.budget_fraction <= 1):
            raise ValueError("budget_fraction must be in (0, 1]")


# 子角色目录与预算切片纯函数；子份额来自父额度，注册不启动线程/远端 Agent。
class SubAgentRegistry:
    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
    def __init__(self) -> None:
        # _roles：已登记子角色元数据；不代表已有并行运行后端。
        self._roles: dict[str, SubAgentSpec] = {}

    # 按稳定身份登记显式合同；校验冲突以避免悄悄替换已存在定义。
    def register(self, spec: SubAgentSpec) -> None:
        if spec.role_id in self._roles:
            raise ValueError(f"duplicate sub-agent role: {spec.role_id}")
        self._roles[spec.role_id] = spec

    # 按身份取得已登记数据；缺失身份显式失败，调用方不能据此捏造已存在对象。
    def get(self, role_id: str) -> SubAgentSpec:
        return self._roles[role_id]

    # 按明确角色 budget_fraction 对父各 meter 向下取整；不启动子 Run 或突破父硬上限。
    def child_budget(
        self, role_id: str, parent_budget: dict[str, int]
    ) -> dict[str, int]:
        fraction = self.get(role_id).budget_fraction
        return {
            meter: max(0, int(amount * fraction))
            for meter, amount in parent_budget.items()
        }
