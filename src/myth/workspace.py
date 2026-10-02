"""Workspace composition root for product, control and durable execution."""

from .adapters.workspace_store import SqliteWorkspaceRepository
from .adapters.conversation_execution import LocalConversationExecution
from .application.conversation_agent import ConversationAgent
from .platform import MythKernel
from .platform.control_store import SqliteControlPlane
from .platform.memory_store import SqliteMemoryStore


class Workspace:
    def __init__(self, runtime):
        self.kernel = MythKernel.default()
        self.repository = SqliteWorkspaceRepository(runtime)
        self.control = SqliteControlPlane(runtime, self.repository)
        self.memory = SqliteMemoryStore(runtime)
        self.execution = LocalConversationExecution(
            runtime,
            self.repository,
            capability_registry=self.kernel.capabilities,
        )
        self.agent = ConversationAgent(
            self.repository,
            self.execution,
            control=self.control,
            memory=self.memory,
        )

    def run(self, rid, provider):
        return self.agent.run(rid, provider)
