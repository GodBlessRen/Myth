"""Exact Agent 当前使用的仓储与执行端口合同。
应用依赖这些协议，仓储实现原子状态提交，执行适配器实现受管 I/O；声明一个端口不表示已有可用后端。"""

from __future__ import annotations
from typing import Any, Protocol
from .models import StepDecision


# Exact 用例状态端口；实现方原子保存步骤/决定/验收投影，应用不持有连接。
class AgentRepository(Protocol):
    # 创建 Exact 用例并冻结验收/预算；具体持久步骤由仓储实现，稳定重试不得覆盖不同意图。
    def create(self, spec: dict[str, Any], manifest: dict[str, Any]) -> str: ...

    # 读取用例行并校验身份存在；不暴露可修改 SQL 游标给应用。
    def row(self, run_id: str) -> dict[str, Any]: ...

    # 按持久顺序读取用例经历；用于上下文恢复而不是权限推断。
    def notes(self, run_id: str) -> list[dict[str, Any]]: ...

    # 取得该 Run 创建时固定的验收合同；后续决策不能改写目标来制造 PASS。
    def manifest(self, run_id: str) -> dict[str, Any]: ...

    # 原子分配或复用当前未完成步骤；耗尽步数返回空值，恢复不跳过未消费的决定。
    def begin_step(self, run_id: str) -> dict[str, Any] | None: ...

    # 把固定步骤与已记录决定绑定；恢复复用同一身份，不能覆盖成另一个提案。
    def bind_decision(
        self, run_id: str, step: int, decision_id: str, decision: StepDecision
    ) -> None: ...

    # 原子记录步骤结果、笔记和下一状态；提交后驱动器再规划下一步。
    def finish_step(
        self,
        run_id: str,
        step: int,
        kind: str,
        payload: dict[str, Any],
        status: str = "RUNNING",
    ) -> None: ...

    # 持久记录阻塞/结束状态及原因；不抹掉已签发凭证和晚到收据。
    def block(self, run_id: str, status: str, reason: str) -> None: ...

    # 按当前持久状态重新进入驱动；恢复核对由执行端口负责，不凭重开动作重发未知效果。
    def reopen(self, run_id: str) -> None: ...

    # 校验待答问题身份并消费明确用户回答；不同问题不能相互代答。
    def answer(self, run_id: str, question_id: str, text: str) -> None: ...

    # 记录停止未来工作的意图/状态；已发出效果仍按实际结果结算。
    def cancel(self, run_id: str) -> None: ...

    # 只有固定验收通过才提交候选、报告与交付投影；completion claim 本身不够。
    def verify_and_deliver(
        self,
        run_id: str,
        step: int,
        verdict: str,
        reason: str,
        decision: StepDecision,
        candidate: dict[str, str],
    ) -> None: ...

    # 读取当前持久事实并生成状态投影；不得把模型 claim 当作已执行或已验收。
    def status(self, run_id: str) -> dict[str, Any]: ...


# Exact I/O 与恢复端口；实现方负责受管范围、模型去重、效果收据与核对。
class AgentExecution(Protocol):
    # 取得一个 Run 的本机执行互斥作用域；竞争不表示效果失败，需按恢复事实判断后续。
    def lock(self, run_id: str) -> Any: ...

    # 固定步骤请求身份，读取/生成持久决定；供应商结果不明时先恢复而非重新调用。
    def request_decision(
        self, run_id: str, step: int, provider: Any, context: str
    ) -> tuple[str, StepDecision]: ...

    # 执行已校验/准入的工作并留下结果证据；已存在稳定绑定时复用事实而非重复效果。
    def execute(
        self, run_id: str, decision_id: str, decision: StepDecision
    ) -> dict[str, Any]: ...

    # 用已有请求、Ticket、收据和对象核对执行状态；没有足够事实时保留 UNKNOWN，不盲目重发。
    def recover(self, run_id: str) -> bool: ...

    # 读取受管候选的当前摘要；不重新读取用户原文件改变冻结基线。
    def current(self, run_id: str) -> dict[str, str]: ...

    # 投影该 Run 的真实工具收据与来源；只提供已记录证据，不替模型声明补造效果。
    def evidence(self, run_id: str) -> dict[str, dict[str, Any]]: ...
