"""子 Agent 的隔离执行合同与预算分配原语。
父 Agent 负责决定是否委派，Runtime 保留权限与预算边界；隔离 worker 使用共同引擎，只可分页读取本次输入。
"""

from __future__ import annotations

from dataclasses import dataclass


# 显式子角色与预算/上下文边界合同；角色登记不代表已经启动子工作。
@dataclass(frozen=True)
class SubAgentSpec:
    # role_id：子 Agent 角色身份；不代表已经启动子工作。
    role_id: str
    # instruction：角色的显式工作说明；不能覆盖父授权上限。
    instruction: str
    # capability_allowlist：角色明确允许能力集合；隔离 worker 仅允许分页读取固定输入。
    capability_allowlist: tuple[str, ...]
    # max_steps：子工作规划步硬上限；实际步数由冻结槽位配置收紧。
    max_steps: int = 6
    # budget_fraction：从父额度分配的比例，范围 (0,1]；按 meter 向下取整。
    budget_fraction: float = 0.25
    # max_task_chars：父 Agent 可委派任务文本的字符上限。
    max_task_chars: int = 4000
    # max_context_chars：显式委派上下文字符上限；完整父对话不会自动继承。
    max_context_chars: int = 12000
    # max_expected_output_chars：期望输出描述的字符上限。
    max_expected_output_chars: int = 2000
    # max_source_refs：允许传入的已结算父级来源引用数量上限。
    max_source_refs: int = 20

    # 在合同构造时校验输入边界；非法值提前拒绝，避免进入后续执行或比较。
    def __post_init__(self) -> None:
        if not self.role_id or self.max_steps <= 0:
            raise ValueError("invalid sub-agent spec")
        if not (0 < self.budget_fraction <= 1):
            raise ValueError("budget_fraction must be in (0, 1]")
        if min(
            self.max_task_chars,
            self.max_context_chars,
            self.max_expected_output_chars,
            self.max_source_refs,
        ) <= 0:
            raise ValueError("sub-agent text/source limits must be positive")


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

    # 返回稳定排序的角色合同；目录可观测不等于角色已经运行。
    def list(self) -> tuple[SubAgentSpec, ...]:
        return tuple(self._roles[key] for key in sorted(self._roles))

    # 按明确角色 budget_fraction 对父各 meter 向下取整；不启动子 Run 或突破父硬上限。
    def child_budget(
        self, role_id: str, parent_budget: dict[str, int]
    ) -> dict[str, int]:
        fraction = self.get(role_id).budget_fraction
        return {
            meter: max(0, int(amount * fraction))
            for meter, amount in parent_budget.items()
        }


# 登记第一版通用隔离 worker；它只有模型推理能力，没有工具、写入或递归委派权限。
def default_subagents() -> SubAgentRegistry:
    registry = SubAgentRegistry()
    registry.register(
        SubAgentSpec(
            role_id="isolated_worker",
            instruction=(
                "在隔离上下文中完成一个子任务；仅可读取显式输入，不得写入、"
                "请求用户或再次委派。"
            ),
            capability_allowlist=("input.read",),
            max_steps=8,
            budget_fraction=0.5,
        )
    )
    return registry
