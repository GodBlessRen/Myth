"""产品组件与架构地图的装配登记。
连接内存目录和策略定义，输出观测元数据；此对象既不是业务 Runtime，也不能授予执行权限，planned 不代表已有执行器。"""

from __future__ import annotations

from dataclasses import dataclass

from .capabilities import CapabilityRegistry, default_capabilities
from .contracts import ArchitectureItem, Maturity
from .observability import TraceProjection
from .retrieval import RetrievalBackend, RetrievalMode, RetrievalRouter
from .subagents import SubAgentRegistry, default_subagents
from ..domains.coordination import StrategyRegistry, default_strategies


CORE: tuple[ArchitectureItem, ...] = (
    ArchitectureItem(
        "goal",
        "Goal",
        "core",
        Maturity.CONNECTED,
        "Long-lived intent owns durable work state across Runs/Sessions. Explicit local timers and intervals admit bounded work while the Web service runs.",
    ),
    ArchitectureItem(
        "run",
        "Run",
        "core",
        Maturity.USABLE,
        "Durable execution lifetime with execution cursor, checkpoint recovery and driver lease boundary.",
    ),
    ArchitectureItem(
        "action",
        "Action",
        "core",
        Maturity.USABLE,
        "Stable intent for one atomic effect or read.",
        ("run",),
    ),
    ArchitectureItem(
        "attempt",
        "Attempt",
        "core",
        Maturity.USABLE,
        "One actual execution opportunity for an Action.",
        ("action",),
    ),
    ArchitectureItem(
        "ticket",
        "Ticket",
        "core",
        Maturity.USABLE,
        "Durable authority to start one Attempt; not success proof.",
        ("attempt",),
    ),
    ArchitectureItem(
        "receipt",
        "Receipt",
        "core",
        Maturity.USABLE,
        "Durable fact about what an issued Attempt actually produced.",
        ("ticket",),
    ),
    ArchitectureItem(
        "artifact",
        "Artifact",
        "core",
        Maturity.USABLE,
        "Content-addressed immutable output/evidence.",
        ("receipt",),
    ),
    ArchitectureItem(
        "verification",
        "Verification",
        "core",
        Maturity.USABLE,
        "Independent acceptance bound to fixed artifacts/evidence.",
        ("receipt", "artifact"),
    ),
)


DOMAINS: tuple[ArchitectureItem, ...] = (
    ArchitectureItem(
        "coordination",
        "Coordination / 统筹",
        "domain",
        Maturity.USABLE,
        "Choose how work is organized; conservative Intent Pick supports deterministic arithmetic and local-retrieval routing, while unmatched work falls back safely.",
        ("goal", "run"),
    ),
    ArchitectureItem(
        "control",
        "Control / 控制",
        "domain",
        Maturity.USABLE,
        "Steer, pause, resume, stop, model/thinking switch and context compact at safe points.",
        ("run",),
    ),
    ArchitectureItem(
        "execution",
        "Execution / 执行",
        "domain",
        Maturity.USABLE,
        "Dispatch admitted work to model/tool/file/git executors and reconcile outcomes.",
        ("attempt", "ticket", "receipt"),
    ),
    ArchitectureItem(
        "capability",
        "Capability / 能力",
        "domain",
        Maturity.USABLE,
        "Discover/version/admit capabilities without turning discovery into authority.",
        ("ticket",),
    ),
    ArchitectureItem(
        "state",
        "State / 状态",
        "domain",
        Maturity.USABLE,
        "Own durable Runs, budgets, commands, events and product records.",
        ("run",),
    ),
    ArchitectureItem(
        "context",
        "Context / 上下文",
        "domain",
        Maturity.USABLE,
        "Build bounded provenance-aware projections. Knowledge resolves one fixed source/digest across L0 metadata, L1 chunk navigation and L2 detailed evidence.",
        ("run",),
    ),
    ArchitectureItem(
        "memory",
        "Memory / 记忆",
        "domain",
        Maturity.USABLE,
        "Versioned working/episodic/semantic/procedural records with provenance/revoke. Recall scans the full visible active candidate set with project/session scope and fact level; Information Delta is not yet a lifecycle engine.",
        ("context",),
    ),
    ArchitectureItem(
        "personal",
        "Personal State / 个人状态",
        "domain",
        Maturity.CONNECTED,
        "Explicit Goals, Triggers, preferences and permissions for long-lived personal agents.",
        ("goal",),
    ),
    ArchitectureItem(
        "observability",
        "Observability / 观测",
        "domain",
        Maturity.USABLE,
        "Persistent third-column observatory projects Goal, execution flow, recovery cursor/driver lease, trajectory, token/context windows, tool calls, control and budgets without owning truth.",
        ("state",),
    ),
    ArchitectureItem(
        "evaluation",
        "Evaluation / 评测",
        "domain",
        Maturity.USABLE,
        "Versioned executable suites plus a durable local Eval Ledger, paired policy comparisons and release gate; no automatic policy promotion.",
        ("observability",),
    ),
    ArchitectureItem(
        "evolution",
        "Evolution / 演进",
        "domain",
        Maturity.USABLE,
        "Durable candidate registry, full-suite release evidence, explicit promote/rollback and future-Turn active policy pointer; never auto-publishes into a live Turn.",
        ("evaluation",),
    ),
)


ADAPTERS: tuple[ArchitectureItem, ...] = (
    ArchitectureItem(
        "chat_ui",
        "Chat / Web UI",
        "adapter",
        Maturity.USABLE,
        "Conversation is an inbound product/channel adapter, not the Runtime core.",
    ),
    ArchitectureItem(
        "sqlite", "SQLite", "adapter", Maturity.USABLE, "Local durable state adapter."
    ),
    ArchitectureItem(
        "local_files",
        "Local Files",
        "adapter",
        Maturity.USABLE,
        "Scoped UTF-8/project/output execution adapter.",
    ),
    ArchitectureItem(
        "milvus",
        "Milvus Vector DB",
        "adapter",
        Maturity.CONNECTED,
        "Optional derived vector-index adapter; SQLite/object storage stays authoritative and lexical retrieval remains the safe fallback.",
    ),
    ArchitectureItem(
        "ollama", "Ollama", "adapter", Maturity.USABLE, "Local model provider adapter."
    ),
    ArchitectureItem(
        "openai",
        "OpenAI API Key",
        "adapter",
        Maturity.CONNECTED,
        "Remote Responses provider; API key uses secure OS credentials or explicit environment configuration.",
    ),
    ArchitectureItem(
        "chatgpt_oauth",
        "Sign in with ChatGPT",
        "adapter",
        Maturity.USABLE,
        "Myth-owned OSS OAuth with PKCE/OIDC, secure OS credential storage, refresh rotation and revoke/logout.",
    ),
    ArchitectureItem(
        "timer_webhook",
        "Local Goal Timer",
        "adapter",
        Maturity.CONNECTED,
        "Explicit one-shot/interval schedules commit wakeup and Turn together. Webhook/email remain planned.",
    ),
)


@dataclass
class MythComponents:
    """产品能力与架构地图的组合登记；默认目录可替换，但不能作为权限或效果账本。"""

    # capabilities：能力目录协作对象；不等于运行效果账本。
    capabilities: CapabilityRegistry
    # retrieval：检索路由协作对象；具体生产召回由仓储实现。
    retrieval: RetrievalRouter
    # subagents：子角色目录协作对象；执行仍由对话适配器在 Runtime 边界内显式派发。
    subagents: SubAgentRegistry
    # observability：Web 第三栏实际使用的只读执行图投影；业务状态仍由仓储拥有。
    observability: TraceProjection
    # strategies：同级组织策略目录；不构成强制串行层。
    strategies: StrategyRegistry

    # 装配默认组件/目录；只登记实际接入项，不启动业务工作或外部执行。
    @classmethod
    def default(cls, *, milvus_ready: bool = False) -> "MythComponents":
        return cls(
            capabilities=default_capabilities(),
            retrieval=RetrievalRouter(
                (
                    RetrievalBackend("local-lexical", RetrievalMode.KEYWORD, True),
                    RetrievalBackend("milvus", RetrievalMode.VECTOR, bool(milvus_ready)),
                    RetrievalBackend("lexical+milvus", RetrievalMode.HYBRID, bool(milvus_ready)),
                )
            ),
            subagents=default_subagents(),
            observability=TraceProjection(),
            strategies=default_strategies(),
        )

    # 输出组件架构投影；注册能力仍需各自执行适配器，不授予权限。
    def snapshot(self) -> dict[str, object]:
        from .. import __version__

        strategy_rows = [
            {
                "id": spec.strategy_id,
                "label": spec.label,
                "kind": "strategy",
                "maturity": spec.state.value,
                "responsibility": spec.responsibility,
            }
            for spec in self.strategies.list()
        ]
        return {
            "version": __version__,
            "shape": "core-domains-strategies-adapters",
            "principle": "fix facts and boundaries; keep intelligence organization pluggable",
            "core": [item.as_dict() for item in CORE],
            "domains": [item.as_dict() for item in DOMAINS],
            "strategies": strategy_rows,
            "adapters": [item.as_dict() for item in ADAPTERS],
            "capabilities": [
                {
                    "id": spec.capability_id,
                    "version": spec.version,
                    "family": spec.family,
                    "risk": spec.risk,
                    "state": spec.state.value,
                }
                for spec in self.capabilities.list()
            ],
            "executable_capabilities": list(self.capabilities.executable_ids()),
            "retrieval": [
                {
                    "id": backend.backend_id,
                    "mode": backend.mode.value,
                    "ready": backend.ready,
                }
                for backend in self.retrieval.backends
            ],
        }
