"""对话产品的装配根。
按状态所有权连接个人、工作区、Control、Memory、Evolution 和执行适配器；应用只得到端口，活动策略仅影响未来 Turn。"""

from .adapters.workspace_store import SqliteWorkspaceRepository
from .adapters.milvus_retrieval import create_milvus_vector_index
from .adapters.conversation_execution import LocalConversationExecution
from .adapters.personal_store import SqlitePersonalState
from .application.conversation_agent import ConversationAgent
from .platform import MythComponents
from .platform.control_store import SqliteControlService
from .platform.memory_store import SqliteMemoryStore
from .platform.knowledge_views import SqliteKnowledgeViews
from .platform.evolution_store import SqliteEvolutionControl
from .delivery import DeliveryLedger
from .mental_model_refresh import MentalModelRefreshScheduler
from .sota_route import SotaRouteLedger
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
        evaluation_harness_mechanisms=None,
    ):
        # vector_index：可选 Milvus 派生索引；延迟连接/加载，缺失时词面检索保持完整可用。
        self.vector_index = create_milvus_vector_index(runtime)
        # components：横向能力组合目录；运行状态仍归具体仓储，目录不授予执行权。
        self.components = MythComponents.default(
            milvus_ready=bool(
                self.vector_index
                and self.vector_index.status().get("healthy")
            )
        )

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
            vector_index=self.vector_index,
            evaluation_harness_mechanisms=evaluation_harness_mechanisms,
        )
        # sota_route：已验收成功路径的效率账本；只给未来 Run 提供冻结提示，不授予能力。
        self.sota_route = SotaRouteLedger(runtime)
        self.repository.sota_route = self.sota_route
        # control：控制服务协作对象；只在安全点影响未来规划。
        self.control = SqliteControlService(runtime, self.repository)
        # memory：有来源记忆协作对象；不授予权限。
        self.memory = SqliteMemoryStore(runtime, vector_index=self.vector_index)
        # knowledge_views：Memory Domain 的派生高阶视图；Mental Model 持有内容视图，Knowledge Page 只持有树结构。
        self.knowledge_views = SqliteKnowledgeViews(runtime, self.memory)
        # mental_model_refresh：只拥有自动刷新 policy/occurrence；模型效果仍走 Core Run + DecisionRuntime。
        self.mental_model_refresh = MentalModelRefreshScheduler(self)
        # delivery：回答终态、验收、Work item 与人工关注的持久交付账本。
        self.delivery = DeliveryLedger(runtime, sota_route=self.sota_route)
        # execution：用例执行端口/实现；外部效果须经过 Ticket 和收据协议。
        self.execution = LocalConversationExecution(
            runtime,
            self.repository,
            capability_registry=self.components.capabilities,
            subagent_registry=self.components.subagents,
            memory_store=self.memory,
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

    # 驱动当前用例并依据持久事实推进；恢复、权限、预算与结束条件见本模块具体协作边界。
    def run(self, rid, provider):
        return self.agent.run(rid, provider)
