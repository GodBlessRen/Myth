"""装配入口：Workspace 继续提供当前工作区能力，同时暴露统一 MythKernel。"""

from .adapters.workspace_store import SqliteWorkspaceRepository
from .adapters.conversation_execution import LocalConversationExecution
from .application.conversation_agent import ConversationAgent
from .platform import MythKernel


class Workspace:
    def __init__(self,runtime):
        self.repository=SqliteWorkspaceRepository(runtime)
        self.execution=LocalConversationExecution(runtime,self.repository)
        self.agent=ConversationAgent(self.repository,self.execution)
        # Breadth-first platform composition.  Kernel registries do not bypass
        # the durable repository/execution path; they describe and organize it.
        self.kernel=MythKernel.default()

    def run(self,rid,provider):return self.agent.run(rid,provider)
