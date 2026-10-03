"""Exact Agent 的公开装配入口。
为 CLI/Web 连接仓储、执行适配器与纯应用驱动器；允许文件与验收在创建时冻结，正常聊天不走这里的语义验收。"""

from __future__ import annotations
import uuid
from .adapters.agent_execution import LocalAgentExecution
from .adapters.agent_store import SqliteAgentRepository
from .application.agent import AgentDriver


# 公开 Exact Agent 门面；构造时装配仓储和执行器，运行逻辑交给应用 Driver。
class AgentRuntime:
    # 复用给定 Runtime 装配 Exact 仓储、执行器和应用；构造不创建用户 Run 或签发 Ticket。
    def __init__(self, runtime):
        # runtime：共享 Runtime 装配对象；其 SQLite 连接只在所属线程使用。
        self.runtime = runtime
        # repository：用例仓储端口/实现；持久状态写入归此协作对象所有。
        self.repository = SqliteAgentRepository(runtime)
        # execution：用例执行端口/实现；外部效果须经过 Ticket 和收据协议。
        self.execution = LocalAgentExecution(runtime, self.repository)
        # driver：纯应用用例驱动器；具体 I/O 通过已装配端口。
        self.driver = AgentDriver(self.repository, self.execution)

    # 校验明确 Goal/模型/步数和允许文件，再冻结验收并交仓储创建；request_id 是业务重试身份。
    def create_run(
        self,
        *,
        goal,
        provider,
        model,
        allowed_files,
        max_steps=6,
        max_output_tokens=1024,
        thinking=None,
        request_id=None,
        acceptance=None,
        provider_options=None,
    ):
        if not isinstance(goal, str) or not goal.strip() or not model.strip():
            raise ValueError("goal and model must be non-empty")
        if type(max_steps) is not int or not 2 <= max_steps <= 64:
            raise ValueError("max_steps must be between 2 and 64")
        if type(max_output_tokens) is not int or not 16 <= max_output_tokens <= 32768:
            raise ValueError("max_output_tokens must be between 16 and 32768")
        if acceptance is not None and not isinstance(acceptance, list):
            raise ValueError("acceptance must be an array of exact replacement rules")
        run_id = f"run_{uuid.uuid4().hex}"
        files, manifest = self.execution.freeze(run_id, allowed_files, acceptance or [])
        spec = {
            "run_id": run_id,
            "request_id": request_id or f"req_{uuid.uuid4().hex}",
            "goal": goal.strip(),
            "provider_id": provider.provider_id,
            "model_id": model,
            "allowed_files": [str(p) for p in files],
            "max_steps": max_steps,
            "max_output_tokens": max_output_tokens,
            "thinking": thinking,
            "provider_options": provider_options or {},
        }
        return self.repository.create(spec, manifest)

    # 驱动当前用例并依据持久事实推进；恢复、权限、预算与结束条件见本模块具体协作边界。
    def run(self, run_id, provider):
        return self.driver.run(run_id, provider)

    # 先验证固定供应商及 pending question 身份，再消费明确用户回答并继续同 Run。
    def resume(self, run_id, provider, user_text, *, question_id):
        if provider.provider_id != self.repository.row(run_id)["provider_id"]:
            raise ValueError("provider must match this run before consuming an answer")
        self.repository.answer(run_id, question_id, user_text)
        return self.run(run_id, provider)

    # 记录停止未来工作的意图/状态；已发出效果仍按实际结果结算。
    def cancel(self, run_id):
        self.repository.cancel(run_id)
        return self.status(run_id)

    # 读取当前持久事实并生成状态投影；不得把模型 claim 当作已执行或已验收。
    def status(self, run_id):
        return self.repository.status(run_id)

    # 读取有界 Run 列表供产品/CLI 展示；这是历史投影，不重新驱动任何 Run。
    def list_runs(self, limit=50):
        return self.repository.list_runs(limit)
