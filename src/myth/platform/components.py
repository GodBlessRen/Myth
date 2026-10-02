"""Composable Myth architecture map.

Myth fixes durable facts/boundaries but does not fix how intelligence is
organized.  Core, Domains, Strategies and Adapters are orthogonal categories,
not a mandatory sequential pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from .capabilities import CapabilityRegistry, default_capabilities
from .context import ContextCompiler
from .control import ControlService
from .contracts import ArchitectureItem, Maturity
from .memory import MemoryCatalog
from .mcp import MCPRegistry
from .observability import TraceProjection
from .retrieval import RetrievalBackend, RetrievalMode, RetrievalRouter
from .skills import SkillRegistry
from .subagents import SubAgentRegistry
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
    ArchitectureItem("chat_ui", "Chat / Web UI", "adapter", Maturity.USABLE, "Conversation is an inbound product/channel adapter, not the Runtime core."),
    ArchitectureItem("sqlite", "SQLite", "adapter", Maturity.USABLE, "Local durable state adapter."),
    ArchitectureItem("local_files", "Local Files", "adapter", Maturity.USABLE, "Scoped UTF-8/project/output execution adapter."),
    ArchitectureItem("ollama", "Ollama", "adapter", Maturity.USABLE, "Local model provider adapter."),
    ArchitectureItem("openai", "OpenAI API Key", "adapter", Maturity.CONNECTED, "Remote Responses provider; API key is read from the environment and never persisted."),
    ArchitectureItem("chatgpt_oauth", "Sign in with ChatGPT", "adapter", Maturity.USABLE, "Myth-owned OSS OAuth with PKCE/OIDC, secure OS credential storage, refresh rotation and revoke/logout."),
    ArchitectureItem("mcp", "MCP", "adapter", Maturity.EXISTS, "External tool/resource discovery maps into local Capability identities."),
    ArchitectureItem("a2a", "A2A", "adapter", Maturity.PLANNED, "Remote Agent interoperability behind AgentPort."),
    ArchitectureItem("browser", "Browser", "adapter", Maturity.PLANNED, "Browser executor behind ExecutionPort."),
    ArchitectureItem("shell", "Shell", "adapter", Maturity.PLANNED, "Bounded command profiles behind ExecutionPort; arbitrary shell is not admitted."),
    ArchitectureItem("timer_webhook", "Local Goal Timer", "adapter", Maturity.CONNECTED, "Explicit one-shot/interval schedules commit wakeup and Turn together. Webhook/email remain planned."),
)


@dataclass
class MythComponents:
    """Composition registry for product/runtime capabilities.

    This is not the Runtime itself and does not grant execution authority.
    """

    control: ControlService
    capabilities: CapabilityRegistry
    context: ContextCompiler
    memory: MemoryCatalog
    retrieval: RetrievalRouter
    subagents: SubAgentRegistry
    skills: SkillRegistry
    mcp: MCPRegistry
    observability: TraceProjection
    strategies: StrategyRegistry

    @classmethod
    def default(cls) -> "MythComponents":
        return cls(
            control=ControlService(),
            capabilities=default_capabilities(),
            context=ContextCompiler(),
            memory=MemoryCatalog(),
            retrieval=RetrievalRouter((
                RetrievalBackend("local-lexical", RetrievalMode.KEYWORD, True),
                RetrievalBackend("vector", RetrievalMode.VECTOR, False),
                RetrievalBackend("hybrid", RetrievalMode.HYBRID, False),
                RetrievalBackend("graph", RetrievalMode.GRAPH, False),
            )),
            subagents=SubAgentRegistry(),
            skills=SkillRegistry(),
            mcp=MCPRegistry(),
            observability=TraceProjection(),
            strategies=default_strategies(),
        )

    def snapshot(self) -> dict[str, object]:
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
            "version": "0.20-recovery-first-runtime",
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
                {"id": backend.backend_id, "mode": backend.mode.value, "ready": backend.ready}
                for backend in self.retrieval.backends
            ],
        }
