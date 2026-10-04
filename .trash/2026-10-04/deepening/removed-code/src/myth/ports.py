以下是已淘汰片段，只作开发留档，不可导入。



class DecisionPort(Protocol):
    """决策提案端口；输出不具有执行授权，具体成熟度按装配证据判断。"""

    # 生成下一步决策提案；实现方固定请求身份，返回值仍需本地参数/权限校验。
    def decide(self, context: dict[str, Any]) -> Any: ...


class ExecutionPort(Protocol):
    """已准入工作执行端口；返回效果数据，Runtime 负责身份与结算。"""

    # 执行已校验/准入的工作并留下结果证据；已存在稳定绑定时复用事实而非重复效果。
    def execute(self, work: dict[str, Any]) -> dict[str, Any]: ...


# 有来源记忆的检索/写入端口；内容不能改变权限或自动成为验收证据。
class MemoryPort(Protocol):
    # 读取当前作用域的检索结果；相似度只用于排序，不升级为已验证事实。
    def search(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]: ...

    # 按明确来源写记忆记录；事实等级与作用域由实现合同校验，不扩大权限。
    def remember(self, **record: Any) -> dict[str, Any]: ...


class EventPort(Protocol):
    """入站事件源端口；事件提议未来工作，实际准入仍需 Runtime。"""

    # 读取入站事件提案；事件源不拥有创建效果或自动授权的权力。
    def poll(self) -> list[dict[str, Any]]: ...


# 显式审批数据端口；批准范围需由本地准入校验，不能接受模型自批。
class ApprovalPort(Protocol):
    # 请求明确用户/系统审批范围；实现方保留审批身份，本地准入仍需验证范围。
    def request_approval(self, request: dict[str, Any]) -> dict[str, Any]: ...


class AgentPort(Protocol):
    """远端/托管 Agent 的可替换边界；声明协议不证明已有 production integration。"""

    # 驱动当前用例并依据持久事实推进；恢复、权限、预算与结束条件见本模块具体协作边界。
    def run(self, request: dict[str, Any]) -> dict[str, Any]: ...


# 不可变字节对象端口；具体实现按摘要校验，不能把路径文本当效果证据。
class ArtifactPort(Protocol):
    # 保存不可变对象并返回内容身份；具体适配器负责原子发布和摘要校验。
    def put(self, data: bytes) -> str: ...

    # 按身份取得已登记数据；缺失身份显式失败，调用方不能据此捏造已存在对象。
    def get(self, digest: str) -> bytes: ...


# 派生观测输出端口；失败可降级且不取得业务状态所有权。
class ObservabilityPort(Protocol):
    # 输出派生观测数据；观测故障不能改写业务结论或补造收据。
    def emit(self, event: dict[str, Any]) -> None: ...


# 长期意图存储端口；身份与生命周期显式管理，Memory 不代替个人状态。
class GoalRepository(Protocol):
    # 校验显式长期意图并同时创建 Goal 和初始工作状态；任一写入失败全项回滚。
    def create_goal(self, title: str, description: str = "") -> dict[str, Any]: ...

    # 按身份读取长期 Goal；工作状态由单独的进度合同表示。
    def goal(self, goal_id: str) -> dict[str, Any]: ...

    # 列出当前可见长期 Goal；归档过滤只影响未来产品导航。
    def goals(self, *, include_archived: bool = False) -> list[dict[str, Any]]: ...


class IntentPickPort(Protocol):
    """处理路径提案端口；可替换规则/模型，不授予能力。"""

    # 从输入与已给上下文选择处理路径；输出是路由提案，具体准入与效果仍由 Runtime 控制。
    def pick(self, value: str, context: dict[str, Any]) -> Any: ...


class InformationResolutionPort(Protocol):
    """固定同源信息的分辨率投影端口；改变表示不改变来源身份。"""

    # 校验范围后解析目标；范围身份来自已准入输入，不能让模型参数扩大权限。
    def resolve(self, source_ref: str, resolution: str) -> Any: ...


class InformationGainPort(Protocol):
    """声明语义的边际增益估计端口；未知值保留未测量，不以相似度冒充价值。"""

    # 按声明估计语义返回增益数据；无证据保持未测量，不能直接 Promote。
    def estimate(self, request: dict[str, Any]) -> Any: ...


class InformationDeltaPort(Protocol):
    """两个信息状态间的变化比较端口；不取得源状态写入权。"""

    # 比较前后信息状态返回变化事实；不表示变化必然有价值，不修改源状态。
    def delta(self, before: Any, after: Any) -> Any: ...


class TextEmbeddingPort(Protocol):
    """文本 embedding 端口；向量只表达召回相似性，不升级事实等级或权限。"""

    # 返回固定 embedding 维度；调用方用它建立兼容向量 schema。
    @property
    def dim(self) -> int: ...

    # 编码权威来源正文用于索引；返回向量不改变原文事实等级。
    def encode_documents(self, documents: list[str]) -> Any: ...

    # 编码查询文本用于召回；相似度只作为候选排序信号。
    def encode_queries(self, queries: list[str]) -> Any: ...


class VectorIndexPort(Protocol):
    """派生向量索引端口；权威正文/版本仍由 SQLite/对象库 hydration 校验。"""

    # 将知识 source version 投影为可重建向量记录；失败不能改变权威文档。
    def sync_knowledge(self, rows: list[dict[str, Any]]) -> dict[str, int]: ...

    # 将 Memory revision 投影为可重建向量记录；失败不能撤销已提交 Memory。
    def sync_memories(self, rows: list[dict[str, Any]]) -> dict[str, int]: ...

    # 返回知识候选身份/版本；调用方必须回权威仓储做 scope/freshness hydration。
    def search_knowledge(self, query: str, *, limit: int = 64) -> list[dict[str, Any]]: ...

    # 返回 Memory 候选身份/版本；相似度不能直接升级事实或权限。
    def search_memories(self, query: str, *, limit: int = 64) -> list[dict[str, Any]]: ...

    # 返回脱敏 Adapter 状态；观测健康不等于业务动作成功。
    def status(self) -> dict[str, Any]: ...
