"""把已知失败标准化为模型可恢复、UI 可观测的数据。
这里只描述失败事实与下一步提示；UNKNOWN/RECONCILE 仍由 Runtime 的 Ticket/Receipt 状态决定。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# FailureObservation：已知失败的稳定投影；message 供人阅读，code/category 供模型、UI 与 Eval 使用。
@dataclass(frozen=True)
class FailureObservation:
    # category：粗粒度失败家族；不等于异常类名，也不改变 Runtime 终态。
    category: str
    # code：稳定机器码；调用方不得依赖可变的人类 message 做控制流。
    code: str
    # message：原始失败的有界人类说明；不得包含凭据或隐藏推理。
    message: str
    # retryable：表示修正输入/上下文后是否值得尝试新机会；不是自动重放授权。
    retryable: bool
    # capability_id：失败涉及的能力身份；空值表示不是工具能力失败。
    capability_id: str | None = None
    # field：已知时指出需要修正的参数字段；未知保持空值。
    field: str | None = None
    # expected：已知时给出合法形状/范围摘要；不是新的权限来源。
    expected: str | None = None
    # hint：给模型/用户的下一步恢复建议；不得要求绕过 Policy。
    hint: str | None = None

    # 生成持久/上下文可用的普通字典；字段名稳定，空值保留便于跨版本解析。
    def serializable(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "capability_id": self.capability_id,
            "field": self.field,
            "expected": self.expected,
            "hint": self.hint,
        }


# 把现有异常收敛为少量稳定语义；特殊规则只识别已存在的明确 Runtime 合同，不猜测外部结果。
def observe_failure(
    exc: BaseException,
    *,
    capability_id: str | None = None,
) -> FailureObservation:
    message = (str(exc) or type(exc).__name__).strip()[:4000]
    lowered = message.lower()
    name = type(exc).__name__

    if lowered.startswith("information control denied:"):
        return FailureObservation(
            "context",
            "information_control_denied",
            message,
            True,
            capability_id,
            hint="Use the already observed evidence, or advance with the returned continuation cursor instead of repeating the same information request.",
        )
    if "sub-agent may only return request_completion" in lowered:
        return FailureObservation(
            "delegation",
            "subagent_contract_rejected",
            message,
            True,
            capability_id,
            expected="request_completion",
            hint="Treat the child as a read-only observation and continue the parent loop without recursive delegation.",
        )
    if "tool is deferred" in lowered:
        return FailureObservation(
            "capability",
            "tool_deferred",
            message,
            True,
            capability_id,
            hint="Call tool.search or tool.describe first; a discovered tool becomes visible on the next model step.",
        )
    if name == "DecisionValidationError":
        return FailureObservation(
            "model_output",
            "decision_invalid",
            message,
            True,
            capability_id,
            hint="Return exactly one decision that matches the advertised response schema.",
        )
    if name == "PatchContractError":
        return FailureObservation(
            "contract",
            "patch_contract_mismatch",
            message,
            True,
            capability_id,
            hint="Read the current source again, then issue a patch whose old_text and expected_count match the observed bytes.",
        )
    if isinstance(exc, PermissionError):
        return FailureObservation(
            "authority",
            "permission_denied",
            message,
            False,
            capability_id,
            hint="Stay inside the admitted project/capability scope; ask the user for an explicit scope change when necessary.",
        )
    if isinstance(exc, ValueError):
        return FailureObservation(
            "validation",
            "invalid_argument",
            message,
            True,
            capability_id,
            hint="Correct the arguments from the failure message and current observations before requesting a new tool opportunity.",
        )
    return FailureObservation(
        "runtime",
        "known_failure",
        message,
        False,
        capability_id,
        hint="Do not claim success. Inspect the durable observations and choose a safe next step.",
    )


# 把结构化失败包装成现有步骤 result；保留 error 字符串兼容旧 UI/测试，同时新增机器可读 failure。
def failure_result(
    observation: FailureObservation,
    *,
    observation_kind: str = "failure",
) -> dict[str, Any]:
    return {
        "error": observation.message,
        "failure": observation.serializable(),
        "observation_kind": observation_kind,
    }
