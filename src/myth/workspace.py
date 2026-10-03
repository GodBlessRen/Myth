"""对话产品的装配根。
按状态所有权连接个人、工作区、Control、Memory、Evolution 和执行适配器；应用只得到端口，活动策略仅影响未来 Turn。"""

from .adapters.workspace_store import SqliteWorkspaceRepository
from .adapters.conversation_execution import LocalConversationExecution
from .adapters.personal_store import SqlitePersonalState
from .application.conversation_agent import ConversationAgent
from .platform import MythComponents
from .platform.control_store import SqliteControlService
from .platform.memory_store import SqliteMemoryStore
from .platform.evolution_store import SqliteEvolutionControl
from .delivery import DeliveryLedger
from .best_path import BestPathLedger
from .strategies import resolution_controller_from_config


# 对话产品装配根；每个 Runtime 连接生成对应适配器实例，不以 UI 缓存替代持久状态。
class Workspace:
    # 按状态所有权顺序装配个人、对话、控制及记忆等适配器，最后把端口交给应用；连接由外层 Runtime 关闭。
    def __init__(
        self,
        runtime,
        *,
        intent_picker=None,
        resolution_controller=None,
        resolution_policy_id=None,
    ):
        # components：横向能力组合目录；运行状态仍归具体仓储，目录不授予执行权。
        self.components = MythComponents.default()
        # 保留旧公开调用方的薄别名；与 components 指向同一对象，不维护另一套状态。
        # kernel：旧公开兼容别名，指向 components；新代码使用 components，避免误认为强制执行层。
        self.kernel = self.components

        # evolution：显式候选/评测/发布状态仓储；不能由模型文字自行 Promote。
        self.evolution = SqliteEvolutionControl(runtime)
        if resolution_controller is None:
            active = self.evolution.active("information_resolution")
            resolution_controller = resolution_controller_from_config(active["config"])
            resolution_policy_id = active["policy_id"]
        else:
            resolution_policy_id = resolution_policy_id or "injected"
        # 先装配个人状态所有者，再将其事务协作接口交给工作区准入协调器。
        # personal：长期意图及进度的状态所有者；对话准入通过显式事务协作加入。
        self.personal = SqlitePersonalState(runtime)
        # repository：用例仓储端口/实现；持久状态写入归此协作对象所有。
        self.repository = SqliteWorkspaceRepository(
            runtime,
            personal=self.personal,
            intent_picker=intent_picker,
            resolution_controller=resolution_controller,
            resolution_policy_id=resolution_policy_id,
        )
        # best_path：已验收成功路径的效率账本；只给未来 Run 提供冻结提示，不授予能力。
        self.best_path = BestPathLedger(runtime)
        self.repository.best_path = self.best_path
        # control：控制服务协作对象；只在安全点影响未来规划。
        self.control = SqliteControlService(runtime, self.repository)
        # memory：有来源记忆协作对象；不授予权限。
        self.memory = SqliteMemoryStore(runtime)
        # delivery：回答终态、验收、Work item 与人工关注的持久交付账本。
        self.delivery = DeliveryLedger(runtime, best_path=self.best_path)
        # execution：用例执行端口/实现；外部效果须经过 Ticket 和收据协议。
        self.execution = LocalConversationExecution(
            runtime,
            self.repository,
            capability_registry=self.components.capabilities,
        )
        # verification：与 execution 共用同一 profile 状态所有者，避免双写真相。
        self.verification = self.execution.verification
        # agent：Exact Agent 用例装配对象；保留固定验收合同。
        self.agent = ConversationAgent(
            self.repository,
            self.execution,
            control=self.control,
            memory=self.memory,
            personal=self.personal,
            delivery=self.delivery,
        )
        # 只补齐已持久化 COMPLETED 回答的派生投影；UNKNOWN 外部效果绝不在这里重放。
        self.delivery.reconcile_pending(
            self.repository, self.memory, self.personal, limit=32
        )
        # 启动只补登记历史 PASSED 路径；不重跑旧模型/工具，也不倒写旧 Turn。
        self.best_path.sync_existing(limit=200)

    # 驱动当前用例并依据持久事实推进；恢复、权限、预算与结束条件见本模块具体协作边界。
    def run(self, rid, provider):
        return self.agent.run(rid, provider)
