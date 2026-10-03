"""供应商无关的模型请求、结果与决策合同。
模型输出是提案，不是效果收据；本地校验负责结构合法性，具体认证和传输留在 providers/auth 适配器。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal


# DecisionType：允许的下一步种类类型别名；形状合法不表示执行授权。
DecisionType = Literal["tool_call", "ask_user", "request_completion"]


class DecisionValidationError(ValueError):
    """传输结构不符合决策合同；持久保留失败反馈，而不将文本直接执行。"""


class ProviderKnownFailure(RuntimeError):
    """供应商给出足够已知失败证据；用量独立结算，不能冒充 UNKNOWN。"""

    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
    def __init__(
        self,
        message: str,
        *,
        usage: dict[str, int] | None = None,
        raw: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        # usage：供应商/执行器测得的各 meter 用量；缺项表示未测量而非零成本。
        self.usage = dict(usage or {})
        # raw：供应商脱敏响应对象；不包含认证请求头或 token。
        self.raw = dict(raw or {})


class ContextTruncated(ProviderKnownFailure):
    """已准入提示达到供应商窗口上限的已知失败；不能信任被截断上下文产生的决定。"""


# 发给模型的不可变角色/文本投影；文本不携带额外执行权限。
@dataclass(frozen=True)
class ModelMessage:
    # role：统一消息角色；system/user/assistant 只约束传输表示。
    role: Literal["system", "user", "assistant"]
    # content：上下文或消息正文；属于数据，不授予 Runtime 权限。
    content: str


# 统一不可变请求合同；窗口、输出上限和投影报告随请求固定，字典字段仍需调用方避免原地修改。
@dataclass(frozen=True)
class ModelRequest:
    # model：明确模型名称；请求创建/控制修订时固定。
    model: str
    # messages：按角色顺序排列的有界模型投影；原始持久历史另存。
    messages: tuple[ModelMessage, ...]
    # response_schema：模型输出传输约束；本地仍要二次校验结构和参数。
    response_schema: dict[str, Any]
    # max_output_tokens：单次生成的输出 Token 上限；须为上下文留出空间。
    max_output_tokens: int = 1024
    # thinking：明确推理选项；None 代表供应商默认，不自动扩预算。
    thinking: str | bool | None = None
    # num_ctx：Ollama Token 窗口大小；与本地字节投影预算近似对齐。
    num_ctx: int | None = None
    # temperature：供应商采样温度，合法范围 0–2；固定温度重复不等于独立样本。
    temperature: float = 0.0
    # 本地 selected/folded/dropped 证据随固定请求保存；供应商只传输其支持的字段。
    # context_report：selected/folded/dropped 与字节预算的本地投影证据；不是 Token 真值。
    context_report: dict[str, Any] | None = None

    # 在合同构造时校验输入边界；非法值提前拒绝，避免进入后续执行或比较。
    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must be non-empty")
        if not self.messages:
            raise ValueError("messages must not be empty")
        if type(self.max_output_tokens) is not int or self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be a positive integer")
        if self.num_ctx is not None and (
            type(self.num_ctx) is not int or self.num_ctx < 1024
        ):
            raise ValueError("num_ctx must be None or an integer >= 1024")
        if (
            not isinstance(self.temperature, (int, float))
            or not 0.0 <= float(self.temperature) <= 2.0
        ):
            raise ValueError("temperature must be between 0 and 2")

    # 生成 JSON 可保存的数据投影；保留身份、版本和单位，不在此授予执行或发布权限。
    def serializable(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in self.messages],
            "response_schema": self.response_schema,
            "max_output_tokens": self.max_output_tokens,
            "thinking": self.thinking,
            "num_ctx": self.num_ctx,
            "temperature": float(self.temperature),
            **(
                {"context_report": self.context_report}
                if self.context_report is not None
                else {}
            ),
        }


# 供应商返回的文本、用量与脱敏传输事实；结果不是工具效果收据。
@dataclass(frozen=True)
class ModelResult:
    # text：正文/模型输出文本；不是执行收据或验收结果。
    text: str
    # usage：供应商/执行器测得的各 meter 用量；缺项表示未测量而非零成本。
    usage: dict[str, int]
    # raw：供应商脱敏响应对象；不包含认证请求头或 token。
    raw: dict[str, Any]
    # response_id：供应商返回的响应身份；可用于追踪，不证明工具效果。
    response_id: str | None = None


# 连通性/认证可用性的观测；ready 不能证明模型语义质量或任务完成。
@dataclass(frozen=True)
class ProviderStatus:
    # provider_id：供应商合同身份；必须匹配 Run/Turn 的固定设置。
    provider_id: str
    # ready：当前服务/后端可用性声明；不证明任务成功。
    ready: bool
    # auth_type：认证方式描述；不携带凭据内容。
    auth_type: str | None = None
    # details：可公开的连接/来源细节；秘钥不得进入。
    details: dict[str, Any] | None = None


# 模型或规则提出的下一步；tool_call/ask_user/completion 仍由本地规则分别校验。
@dataclass(frozen=True)
class StepDecision:
    # decision_type：下一步种类：工具/提问/请求完成；三种分别校验。
    decision_type: DecisionType
    # reason：可解释的选择/拒绝原因；不是授权证据。
    reason: str
    # capability_id：明确本地能力身份；仍须核对版本、状态和准入范围。
    capability_id: str | None = None
    # arguments：模型提出的参数字典；执行器必须校验类型、范围和前置状态。
    arguments: dict[str, Any] | None = None
    # question：待答问题文本；消费回答必须匹配问题身份。
    question: str | None = None
    # missing_info_category：缺信息类别投影；不自动推断用户批准。
    missing_info_category: str | None = None
    # claim：模型的完成声明；只能提出完成请求，不能直接交付。
    claim: str | None = None
    # goal_coverage：模型声明的目标覆盖说明；独立验收仍核对固定合同。
    goal_coverage: str | None = None
    # evidence_refs：固定来源/收据引用集合；文本引用本身不能补造效果。
    evidence_refs: tuple[str, ...] = ()
    # remaining：模型仍列出的未完成项；非空时不能宣称完整 Exact 验收。
    remaining: tuple[str, ...] = ()

    # 生成 JSON 可保存的数据投影；保留身份、版本和单位，不在此授予执行或发布权限。
    def serializable(self) -> dict[str, Any]:
        return {
            "decision_type": self.decision_type,
            "reason": self.reason,
            "capability_id": self.capability_id,
            "arguments": self.arguments,
            "question": self.question,
            "missing_info_category": self.missing_info_category,
            "claim": self.claim,
            "goal_coverage": self.goal_coverage,
            "evidence_refs": list(self.evidence_refs),
            "remaining": list(self.remaining),
        }


# 统一传输形状兼容不同供应商；非当前决定字段留空，arguments_json 避免自由嵌套对象的供应商差异，本地仍要解析校验。
STEP_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "decision_type",
        "reason",
        "capability_id",
        "arguments_json",
        "question",
        "missing_info_category",
        "claim",
        "goal_coverage",
        "evidence_refs",
        "remaining",
    ],
    "properties": {
        "decision_type": {
            "type": "string",
            "enum": ["tool_call", "ask_user", "request_completion"],
        },
        "reason": {"type": "string"},
        "capability_id": {"type": "string"},
        "arguments_json": {"type": "string"},
        "question": {"type": "string"},
        "missing_info_category": {"type": "string"},
        "claim": {"type": "string"},
        "goal_coverage": {"type": "string"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "remaining": {"type": "array", "items": {"type": "string"}},
    },
}


# 校验传输字段为文本并清外围空白；参数内容仍需能力专用校验。
def _text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise DecisionValidationError(f"{field} must be a string")
    return value.strip()


# 校验字符串列表并转换不可变引用集合；空项清理不生成证据。
def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DecisionValidationError(f"{field} must be an array of strings")
    return tuple(item for item in (item.strip() for item in value) if item)


def parse_step_decision(text: str) -> StepDecision:
    """解析统一决定并区分工具/提问/完成字段；wire 兼容映射只改变表示，不授予执行权。"""

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DecisionValidationError("model output is not valid JSON") from exc
    if not isinstance(value, dict):
        raise DecisionValidationError("model output must be a JSON object")

    # 本地对话 wire 使用简短 action；统一投影到同一个领域决策，权限不从 wire 推导。
    if "action" in value and "decision_type" not in value:
        action = _text(value["action"], "action")
        value = {
            **value,
            "decision_type": (
                "request_completion"
                if action == "reply"
                else "ask_user" if action == "ask" else "tool_call"
            ),
            "capability_id": action,
            "goal_coverage": "answer",
        }

    decision_type = _text(value.get("decision_type"), "decision_type")
    if decision_type not in {"tool_call", "ask_user", "request_completion"}:
        raise DecisionValidationError(f"unsupported decision_type: {decision_type}")
    reason = _text(value.get("reason"), "reason")
    if not reason:
        raise DecisionValidationError("reason must be non-empty")

    evidence_refs = _string_tuple(value.get("evidence_refs", []), "evidence_refs")
    remaining = _string_tuple(value.get("remaining", []), "remaining")

    if decision_type == "tool_call":
        capability_id = _text(value.get("capability_id"), "capability_id")
        if not capability_id:
            raise DecisionValidationError("tool_call requires capability_id")
        if "arguments" in value:
            arguments = value["arguments"]
        else:
            arguments_json = _text(value.get("arguments_json"), "arguments_json")
            try:
                arguments = json.loads(arguments_json)
            except json.JSONDecodeError as exc:
                raise DecisionValidationError(
                    "arguments_json must contain valid JSON"
                ) from exc
        if not isinstance(arguments, dict):
            raise DecisionValidationError(
                "tool_call arguments must decode to an object"
            )
        return StepDecision(
            decision_type="tool_call",
            reason=reason,
            capability_id=capability_id,
            arguments=arguments,
        )

    if decision_type == "ask_user":
        question = _text(value.get("question"), "question")
        if not question:
            raise DecisionValidationError("ask_user requires question")
        return StepDecision(
            decision_type="ask_user",
            reason=reason,
            question=question,
            missing_info_category=_text(
                value.get("missing_info_category", ""), "missing_info_category"
            )
            or None,
        )

    claim = _text(value.get("claim"), "claim")
    goal_coverage = _text(value.get("goal_coverage"), "goal_coverage")
    if not claim or not goal_coverage:
        raise DecisionValidationError(
            "request_completion requires claim and goal_coverage"
        )
    return StepDecision(
        decision_type="request_completion",
        reason=reason,
        claim=claim,
        goal_coverage=goal_coverage,
        evidence_refs=evidence_refs,
        remaining=remaining,
    )
