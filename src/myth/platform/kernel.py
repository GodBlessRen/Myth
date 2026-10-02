"""Breadth-first Myth platform composition.

The kernel names the full product shape now while keeping maturity honest.
Existing durable execution remains the authority; planned layers do not become
executable merely because they are registered here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .capabilities import CapabilityRegistry, default_capabilities
from .context import ContextCompiler
from .contracts import LayerState, PlatformLayer
from .control import ControlPlane
from .memory import MemoryCatalog
from .mcp import MCPRegistry
from .observability import TraceProjection
from .retrieval import RetrievalBackend, RetrievalMode, RetrievalRouter
from .skills import SkillRegistry
from .subagents import SubAgentRegistry


LAYERS: tuple[PlatformLayer, ...] = (
    PlatformLayer("P0", "runtime", "Durable Runtime", LayerState.USABLE, "Run/Action/Attempt/Ticket/Receipt/Budget/Verification/Recovery"),
    PlatformLayer("P10", "conversation", "Conversation", LayerState.USABLE, "Multi-turn sessions, projects, attachments and managed outputs", ("runtime",)),
    PlatformLayer("P20", "control", "Control Plane", LayerState.USABLE, "Persistent steer, pause, resume, abort, model/thinking switch and compaction commands", ("runtime", "conversation")),
    PlatformLayer("P30", "capabilities", "Capability Registry", LayerState.USABLE, "Registry-gated file/search/diff/git capability admission", ("runtime",)),
    PlatformLayer("P40", "context", "Context Compiler", LayerState.USABLE, "Typed provenance-aware history projection under a fixed context budget", ("conversation",)),
    PlatformLayer("P50", "memory", "Memory", LayerState.USABLE, "Persistent episodic/semantic/procedural/working revisions with lexical retrieval", ("context",)),
    PlatformLayer("P60", "retrieval", "Retrieval / RAG", LayerState.USABLE, "Keyword retrieval for documents and memory; vector/hybrid/graph stay optional", ("context",)),
    PlatformLayer("P70", "workflow", "Workflow", LayerState.WIRED, "Validated dependency graphs and ready-step scheduling", ("capabilities",)),
    PlatformLayer("P80", "subagents", "SubAgent", LayerState.WIRED, "Role-scoped delegation with capability and budget bounds", ("workflow",)),
    PlatformLayer("P90", "skills", "Skills", LayerState.WIRED, "Reusable procedures separate from tool authority", ("capabilities",)),
    PlatformLayer("P100", "mcp", "MCP", LayerState.WIRED, "External tool discovery mapped into local capability identities", ("capabilities",)),
    PlatformLayer("P110", "observability", "Observability", LayerState.USABLE, "Runtime Inspector projects control, budget, operation and event facts", ("runtime",)),
    PlatformLayer("P120", "evaluation", "Evaluation", LayerState.WIRED, "Fixed suites, quality gates and comparable cost evidence", ("observability",)),
    PlatformLayer("P130", "evolution", "Evolution", LayerState.WIRED, "Candidate policy comparison and explicit release gates", ("evaluation",)),
    PlatformLayer("P1000", "distributed", "Distributed Runtime", LayerState.PLANNED, "Workers, leases, remote execution and multi-user deployment", ("runtime", "control")),
)


@dataclass
class MythKernel:
    control: ControlPlane
    capabilities: CapabilityRegistry
    context: ContextCompiler
    memory: MemoryCatalog
    retrieval: RetrievalRouter
    subagents: SubAgentRegistry
    skills: SkillRegistry
    mcp: MCPRegistry
    observability: TraceProjection

    @classmethod
    def default(cls) -> "MythKernel":
        return cls(
            control=ControlPlane(),
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
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "version": "0.6-skeleton",
            "strategy": "breadth-first",
            "layers": [layer.as_dict() for layer in LAYERS],
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
