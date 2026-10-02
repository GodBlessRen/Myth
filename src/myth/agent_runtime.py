"""装配与兼容入口：CLI/Web 使用本类，纯编排位于 application/agent.py。

在此装配端口适配器，复用 P1/P2 的账户、Ticket 和收据；应用层不持有 SQL。
"""
from __future__ import annotations
import uuid
from .adapters.agent_execution import LocalAgentExecution
from .adapters.agent_store import SqliteAgentRepository
from .application.agent import AgentDriver


class AgentRuntime:
    def __init__(self, runtime):
        self.runtime = runtime
        self.repository = SqliteAgentRepository(runtime)
        self.execution = LocalAgentExecution(runtime, self.repository)
        self.driver = AgentDriver(self.repository, self.execution)

    def create_run(self, *, goal, provider, model, allowed_files, max_steps=6,
                   max_output_tokens=1024, thinking=None, request_id=None, acceptance=None, provider_options=None):
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
        spec = {"run_id": run_id, "request_id": request_id or f"req_{uuid.uuid4().hex}",
                "goal": goal.strip(), "provider_id": provider.provider_id, "model_id": model,
                "allowed_files": [str(p) for p in files], "max_steps": max_steps,
                "max_output_tokens": max_output_tokens, "thinking": thinking, "provider_options": provider_options or {}}
        return self.repository.create(spec, manifest)

    def run(self, run_id, provider):
        return self.driver.run(run_id, provider)

    def resume(self, run_id, provider, user_text, *, question_id):
        if provider.provider_id != self.repository.row(run_id)["provider_id"]:
            raise ValueError("provider must match this run before consuming an answer")
        self.repository.answer(run_id, question_id, user_text)
        return self.run(run_id, provider)

    def cancel(self, run_id):
        self.repository.cancel(run_id)
        return self.status(run_id)

    def status(self, run_id):
        return self.repository.status(run_id)

    def list_runs(self, limit=50):
        return self.repository.list_runs(limit)
