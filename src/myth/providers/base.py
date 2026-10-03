"""模型 I/O 的结构化端口。
供应商只执行传输并返回结果/状态，Runtime 独占准入、Ticket、请求对象、收据和预算结算；检查连通性不证明目标任务完成。"""

from __future__ import annotations

from typing import Protocol

from ..models import ModelRequest, ModelResult, ProviderStatus


# 模型传输协议；统一请求/结果，不允许实现方直接修改 Run 或签发 Ticket。
class ModelProvider(Protocol):
    # provider_id：供应商合同身份；必须匹配 Run/Turn 的固定设置。
    provider_id: str

    # 观察供应商认证/服务是否可用；返回状态而不签发模型 Ticket。
    def check(self) -> ProviderStatus: ...

    # 将已准入统一请求交给具体传输实现，返回模型结果/用量；不拥有业务状态或完成验收。
    def invoke(self, request: ModelRequest) -> ModelResult: ...
