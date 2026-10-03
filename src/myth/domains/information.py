"""Intent 与信息分辨率/增量/增益的纯数据合同。
同源视图、变化事实与边际价值各自表达不同语义；增益成本为显式数据，不从相似度或模型自述推导。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class InformationResolution(StrEnum):
    """同一份信息的细节等级；L0 摘要、L1 导航、L2 原始证据，不表示回答置信度。"""

    # L0：同源轻量摘要/索引表示；来源身份保持固定。
    L0 = "L0"  # abstract / tiny retrieval representation
    # L1：同源有界片段表示；不是完整全文。
    L1 = "L1"  # overview / navigational representation
    # L2：同源全文/分页展开；粒度提高不等于真实性提高。
    L2 = "L2"  # detailed evidence / source-of-truth representation


# 固定来源的投影视图；分辨率可以改变，source/provenance 身份不能被替换。
@dataclass(frozen=True)
class InformationView:
    # source_ref：固定资料/对象/Run 来源身份；分辨率改变时保留原来源。
    source_ref: str
    # resolution：同源表示等级 L0/L1/L2；不是语义置信度。
    resolution: InformationResolution
    # content：上下文或消息正文；属于数据，不授予 Runtime 权限。
    content: str
    # provenance_ref：可追溯来源引用；缺失不能伪装 verified。
    provenance_ref: str | None = None
    # token_estimate：Token 的估算值；None 表示没有测量，不是字节长度。
    token_estimate: int | None = None


@dataclass(frozen=True)
class InformationDelta:
    """两个信息状态间的变化事实；added/updated/removed/conflicted 不等于价值判断。"""

    # added：新增来源/事实身份集合；只表示变化。
    added: tuple[str, ...] = ()
    # updated：已更新来源/事实身份集合；价值另行测量。
    updated: tuple[str, ...] = ()
    # removed：已移除身份集合；历史证据仍可保留。
    removed: tuple[str, ...] = ()
    # conflicted：发生冲突的身份集合；不能静默选择有利版本。
    conflicted: tuple[str, ...] = ()

    # 判断任一变化集合非空；只表达变化事实，不衡量价值。
    @property
    def changed(self) -> bool:
        return any((self.added, self.updated, self.removed, self.conflicted))


@dataclass(frozen=True)
class InformationGain:
    """声明估计语义的边际价值/成本；未校准保留 None，不宣称香农互信息。"""

    # source_ref：固定资料/对象/Run 来源身份；分辨率改变时保留原来源。
    source_ref: str
    # from_resolution：变更前表示等级；None 表示尚无原视图。
    from_resolution: InformationResolution | None
    # to_resolution：计划/估计的目标表示等级，来源仍固定。
    to_resolution: InformationResolution
    # estimated_gain：声明估计语义的边际任务价值；None 表示未校准。
    estimated_gain: float | None = None
    # estimated_cost：显式标量成本；无权重时保留 None。
    estimated_cost: float | None = None
    # estimator：估计器身份/版本，便于解释数值语义。
    estimator: str | None = None

    # 已测增益和非零成本才返回比值；None/零成本不造无限收益。
    @property
    def gain_per_cost(self) -> float | None:
        if self.estimated_gain is None or self.estimated_cost in (None, 0):
            return None
        return self.estimated_gain / self.estimated_cost


class IntentRoute(StrEnum):
    """请求处理路径；路由枚举不改变能力或作用域。"""

    # DIRECT：直接回答路径提案；不放开受管工具执行。
    DIRECT = "direct"
    # LOCAL_RETRIEVAL：词面本地资料路径提案；只使用可见作用域来源。
    LOCAL_RETRIEVAL = "local_retrieval"
    # DETERMINISTIC：有界确定规则路径；规则失败需明确回退，不造模型结果。
    DETERMINISTIC = "deterministic"
    # AGENT：Agent 路径/工作种类声明；实际用例仍受 Runtime 边界约束。
    AGENT = "agent"
    # ASK_USER：需要明确用户信息的路径；答案必须匹配待答问题身份。
    ASK_USER = "ask_user"


@dataclass(frozen=True)
class IntentPick:
    """一次路径选择的不可变提案；confidence 是策略输出，不是语义验收。"""

    # route：处理路径提案；不会改变执行范围。
    route: IntentRoute
    # objective：本次路由的处理目的；不是新的长期授权。
    objective: str | None = None
    # confidence：策略输出置信度；不等于可信验收或信息增益。
    confidence: float | None = None
    # reason：可解释的选择/拒绝原因；不是授权证据。
    reason: str | None = None
    # metadata：合同相关的投影元数据；不得夹带秘钥或隐式权限。
    metadata: dict[str, Any] | None = None
