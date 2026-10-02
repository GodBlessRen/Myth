"""Workspace composition root for product, domains and durable execution."""

from .adapters.workspace_store import SqliteWorkspaceRepository
from .adapters.conversation_execution import LocalConversationExecution
from .adapters.personal_store import SqlitePersonalState
from .application.conversation_agent import ConversationAgent
from .platform import MythComponents
from .platform.control_store import SqliteControlService
from .platform.memory_store import SqliteMemoryStore


class Workspace:
    def __init__(self, runtime, *, intent_picker=None, resolution_controller=None):
        self.components = MythComponents.default()
        # Compatibility alias for v0.6-v0.8 callers.
        self.kernel = self.components

        self.repository = SqliteWorkspaceRepository(
            runtime,
            intent_picker=intent_picker,
            resolution_controller=resolution_controller,
        )
        self.control = SqliteControlService(runtime, self.repository)
        self.memory = SqliteMemoryStore(runtime)
        self.personal = SqlitePersonalState(runtime)
        self.execution = LocalConversationExecution(
            runtime,
            self.repository,
            capability_registry=self.components.capabilities,
        )
        self.agent = ConversationAgent(
            self.repository,
            self.execution,
            control=self.control,
            memory=self.memory,
        )

    def run(self, rid, provider):
        return self.agent.run(rid, provider)
