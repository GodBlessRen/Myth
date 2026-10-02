"""装配入口：工作区用例依赖端口；HTTP 只调用此门面，不持有数据库。"""
from .adapters.workspace_store import SqliteWorkspaceRepository
from .adapters.conversation_execution import LocalConversationExecution
from .application.conversation_agent import ConversationAgent


class Workspace:
    def __init__(self,runtime):
        self.repository=SqliteWorkspaceRepository(runtime)
        self.execution=LocalConversationExecution(runtime,self.repository)
        self.agent=ConversationAgent(self.repository,self.execution)

    def run(self,rid,provider):return self.agent.run(rid,provider)
