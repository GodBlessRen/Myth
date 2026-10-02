"""Workspace composition root for product, domains and durable execution."""

from .adapters.workspace_store import SqliteWorkspaceRepository
from .adapters.conversation_execution import LocalConversationExecution
from .adapters.personal_store import SqlitePersonalState
from .application.conversation_agent import ConversationAgent
from .platform import MythComponents
from .platform.control_store import SqliteControlService
from .platform.memory_store import SqliteMemoryStore
from .platform.evolution_store import SqliteEvolutionControl
from .strategies import resolution_controller_from_config


class Workspace:
    def __init__(
        self,
        runtime,
        *,
        intent_picker=None,
        resolution_controller=None,
        resolution_policy_id=None,
    ):
        self.components = MythComponents.default()
        # Compatibility alias for v0.6-v0.8 callers.
        self.kernel = self.components

        self.evolution = SqliteEvolutionControl(runtime)
        if resolution_controller is None:
            active=self.evolution.active("information_resolution")
            resolution_controller=resolution_controller_from_config(active["config"])
            resolution_policy_id=active["policy_id"]
        else:
            resolution_policy_id=resolution_policy_id or "injected"
        self.repository = SqliteWorkspaceRepository(
            runtime,
            intent_picker=intent_picker,
            resolution_controller=resolution_controller,
            resolution_policy_id=resolution_policy_id,
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
            personal=self.personal,
        )

    def run(self, rid, provider):
        return self.agent.run(rid, provider)
