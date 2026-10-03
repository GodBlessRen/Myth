"""组织工作方式的纯策略合同与登记表。
Direct/Agent/Workflow 等是同级可替换策略，不是强制执行层；登记可用性不等于签发执行 Ticket。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


# 下一步组织目标的纯枚举；选择目标不产生 Ticket 或远端调用。
class RouteTarget(StrEnum):
    # MODEL：模型推理工作种类；仍须固定请求并经过模型 Ticket。
    MODEL = "model"
    # TOOL：本地/远端能力工作种类；仍受准入范围和收据核对约束。
    TOOL = "tool"
    # WORKFLOW：固定图工作种类；图验证不等于节点已执行。
    WORKFLOW = "workflow"
    # AGENT：Agent 路径/工作种类声明；实际用例仍受 Runtime 边界约束。
    AGENT = "agent"
    # REMOTE_AGENT：远端 Agent 工作声明；无适配器时保持规划成熟度。
    REMOTE_AGENT = "remote_agent"
    # HUMAN：明确人工参与工作；不能由模型自行代答审批。
    HUMAN = "human"


# 策略成熟度声明；connected/usable 必须由装配与验证证据支持。
class StrategyState(StrEnum):
    # EXISTS：合同/组件存在，尚不宣称完整产品装配。
    EXISTS = "exists"
    # CONNECTED：当前路径已经装配，真实验证范围另见证据。
    CONNECTED = "connected"
    # USABLE：已有明确可用路径；不能外推为所有场景稳定。
    USABLE = "usable"
    # HARDENED：声明的加固成熟度；需要对应测试和证据支持。
    HARDENED = "hardened"
    # PLANNED：规划中的能力/后端；不会因登记而自动执行。
    PLANNED = "planned"


# 可替换组织策略的描述合同；不是必须顺序经过的执行层。
@dataclass(frozen=True)
class StrategySpec:
    # strategy_id：组织策略身份；策略可替换而 Core 事实保持稳定。
    strategy_id: str
    # label：产品显示名称；不能替代执行状态。
    label: str
    # state：本合同的当前生命周期/成熟度；以所属枚举解释，不混用 Run 与 Goal 状态。
    state: StrategyState
    # responsibility：单一职责说明；描述不代表实现已经完成。
    responsibility: str


class CoordinationStrategy(Protocol):
    """选择未来工作单元的协议；返回提案，Execution/Runtime 才能授予开始资格。"""

    # strategy_id：组织策略身份；策略可替换而 Core 事实保持稳定。
    strategy_id: str

    # 从上下文提出下一工作描述或结束；不拥有执行授权。
    def next_work(self, context: dict[str, Any]) -> dict[str, Any] | None: ...


# 进程内策略描述目录；拒绝重复身份，不拥有持久 Run 或供应商连接。
class StrategyRegistry:
    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
    def __init__(self, specs: tuple[StrategySpec, ...] = ()) -> None:
        # _specs：已登记能力/策略合同；重复身份拒绝，注册不产生 Ticket。
        self._specs: dict[str, StrategySpec] = {}
        for spec in specs:
            self.register(spec)

    # 按稳定身份登记显式合同；校验冲突以避免悄悄替换已存在定义。
    def register(self, spec: StrategySpec) -> None:
        if not spec.strategy_id or spec.strategy_id in self._specs:
            raise ValueError(f"duplicate/empty strategy: {spec.strategy_id}")
        self._specs[spec.strategy_id] = spec

    # 返回当前目录/仓储的可见条目；排序和过滤只生成投影，不授予执行权。
    def list(self) -> tuple[StrategySpec, ...]:
        return tuple(sorted(self._specs.values(), key=lambda item: item.strategy_id))

    # 按身份取得已登记数据；缺失身份显式失败，调用方不能据此捏造已存在对象。
    def get(self, strategy_id: str) -> StrategySpec:
        return self._specs[strategy_id]


# 登记当前组织策略与成熟度；有图合同/角色目录不等于可用并行执行器。
def default_strategies() -> StrategyRegistry:
    return StrategyRegistry(
        (
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
        )
    )
