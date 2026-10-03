"""检索后端可用性与模式的纯路由合同。
关键词、向量、混合和图分别登记；未 ready 的后端不可被选择，这不实现或证明向量索引/Graph 集成。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


# 检索组织模式枚举；VECTOR/HYBRID/GRAPH 声明不能替代已安装后端。
class RetrievalMode(StrEnum):
    # KEYWORD：当前词面检索模式；不冒充向量语义搜索。
    KEYWORD = "keyword"
    # VECTOR：向量后端声明；ready 前不参与选择。
    VECTOR = "vector"
    # HYBRID：混合后端声明；具体实现和评测需独立提供。
    HYBRID = "hybrid"
    # GRAPH：关系图后端声明；不是当前词面检索的别名。
    GRAPH = "graph"


# 后端可用性描述；ready 与 provenance 各自说明连接和来源支持。
@dataclass(frozen=True)
class RetrievalBackend:
    # backend_id：检索后端身份；必须另有 ready 才可选择。
    backend_id: str
    # mode：当前合同的模式枚举；不依名称假定可执行。
    mode: RetrievalMode
    # ready：当前服务/后端可用性声明；不证明任务成功。
    ready: bool
    # provenance：后端是否声明来源支持；不代替具体证据引用。
    provenance: bool = True


# 在 ready 后端中选择模式的纯目录；没有可用后端显式拒绝。
class RetrievalRouter:
    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
    def __init__(self, backends: tuple[RetrievalBackend, ...]) -> None:
        # backends：声明的检索后端序列；只有 ready 后端才进入选择。
        self.backends = backends

    # 仅返回 ready 后端；登记为 planned 的向量/Graph 不参与路由。
    def available(self) -> tuple[RetrievalBackend, ...]:
        return tuple(item for item in self.backends if item.ready)

    # 按 semantic/relational 需求偏好在 ready 后端选取；无可用后端抛 LookupError。
    def choose(
        self, *, semantic: bool = False, relational: bool = False
    ) -> RetrievalBackend:
        ready = self.available()
        preferences = (
            (RetrievalMode.GRAPH, RetrievalMode.HYBRID, RetrievalMode.KEYWORD)
            if relational
            else (
                (RetrievalMode.HYBRID, RetrievalMode.VECTOR, RetrievalMode.KEYWORD)
                if semantic
                else (RetrievalMode.KEYWORD, RetrievalMode.HYBRID)
            )
        )
        for mode in preferences:
            for backend in ready:
                if backend.mode is mode:
                    return backend
        raise LookupError("no retrieval backend is ready")
