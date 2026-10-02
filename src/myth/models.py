"""Provider-neutral model request/response and StepDecision contracts.

The model may propose work, but its output is never an execution receipt. This
module intentionally keeps provider credentials and provider wire formats out
of the domain vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal


DecisionType = Literal["tool_call", "ask_user", "request_completion"]


class DecisionValidationError(ValueError):
    """The model response is syntactically valid JSON but not a valid decision."""


class ProviderKnownFailure(RuntimeError):
    """Provider returned enough evidence to classify the attempt as FAILED, not UNKNOWN."""

    def __init__(self, message: str, *, usage: dict[str, int] | None = None, raw: dict[str, Any] | None = None):
        super().__init__(message)
        self.usage = dict(usage or {})
        self.raw = dict(raw or {})


class ContextTruncated(ProviderKnownFailure):
    """Provider reports that the admitted prompt reached the configured context ceiling."""


@dataclass(frozen=True)
class ModelMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class ModelRequest:
    model: str
    messages: tuple[ModelMessage, ...]
    response_schema: dict[str, Any]
    max_output_tokens: int = 1024
    thinking: str | bool | None = None
    num_ctx: int | None = None
    temperature: float = 0.0
    # Local projection evidence; provider adapters transmit only their supported
    # fields. This report travels with the immutable request for replay/auditing.
    context_report: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must be non-empty")
        if not self.messages:
            raise ValueError("messages must not be empty")
        if type(self.max_output_tokens) is not int or self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be a positive integer")
        if self.num_ctx is not None and (type(self.num_ctx) is not int or self.num_ctx < 1024):
            raise ValueError("num_ctx must be None or an integer >= 1024")
        if not isinstance(self.temperature, (int, float)) or not 0.0 <= float(self.temperature) <= 2.0:
            raise ValueError("temperature must be between 0 and 2")

    def serializable(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in self.messages],
            "response_schema": self.response_schema,
            "max_output_tokens": self.max_output_tokens,
            "thinking": self.thinking,
            "num_ctx": self.num_ctx,
            "temperature": float(self.temperature),
            **({"context_report": self.context_report} if self.context_report is not None else {}),
        }


@dataclass(frozen=True)
class ModelResult:
    text: str
    usage: dict[str, int]
    raw: dict[str, Any]
    response_id: str | None = None


@dataclass(frozen=True)
class ProviderStatus:
    provider_id: str
    ready: bool
    auth_type: str | None = None
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class StepDecision:
    decision_type: DecisionType
    reason: str
    capability_id: str | None = None
    arguments: dict[str, Any] | None = None
    question: str | None = None
    missing_info_category: str | None = None
    claim: str | None = None
    goal_coverage: str | None = None
    evidence_refs: tuple[str, ...] = ()
    remaining: tuple[str, ...] = ()

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


# Fixed transport shape: easier to support consistently across Ollama and
# OpenAI Structured Outputs than a top-level discriminated oneOf. Unused
# fields are empty strings/lists. arguments_json avoids provider-specific
# restrictions around free-form nested objects.
STEP_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "decision_type", "reason", "capability_id", "arguments_json",
        "question", "missing_info_category", "claim", "goal_coverage",
        "evidence_refs", "remaining",
    ],
    "properties": {
        "decision_type": {"type": "string", "enum": ["tool_call", "ask_user", "request_completion"]},
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


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise DecisionValidationError(f"{field} must be a string")
    return value.strip()


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DecisionValidationError(f"{field} must be an array of strings")
    return tuple(item for item in (item.strip() for item in value) if item)


def parse_step_decision(text: str) -> StepDecision:
    """Parse and validate the provider-neutral decision transport object."""

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DecisionValidationError("model output is not valid JSON") from exc
    if not isinstance(value, dict):
        raise DecisionValidationError("model output must be a JSON object")

    # 本地对话 wire 使用简短 action；统一投影到同一个领域决策，权限不从 wire 推导。
    if "action" in value and "decision_type" not in value:
        action=_text(value["action"],"action")
        value={**value,"decision_type":"request_completion" if action=="reply" else "ask_user" if action=="ask" else "tool_call","capability_id":action,"goal_coverage":"answer"}

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
                raise DecisionValidationError("arguments_json must contain valid JSON") from exc
        if not isinstance(arguments, dict):
            raise DecisionValidationError("tool_call arguments must decode to an object")
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
            missing_info_category=_text(value.get("missing_info_category", ""), "missing_info_category") or None,
        )

    claim = _text(value.get("claim"), "claim")
    goal_coverage = _text(value.get("goal_coverage"), "goal_coverage")
    if not claim or not goal_coverage:
        raise DecisionValidationError("request_completion requires claim and goal_coverage")
    return StepDecision(
        decision_type="request_completion",
        reason=reason,
        claim=claim,
        goal_coverage=goal_coverage,
        evidence_refs=evidence_refs,
        remaining=remaining,
    )
