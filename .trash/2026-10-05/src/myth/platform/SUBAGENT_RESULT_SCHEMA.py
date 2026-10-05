"""归档：单次生成 schema 已由共同 StepDecision 引擎替代；不供生产 import。"""
# SUBAGENT_RESULT_SCHEMA：隔离 worker 只能返回完成结果；Schema 限制表示，本地仍会复核决定种类与证据引用。
SUBAGENT_RESULT_SCHEMA: dict[str, object] = {
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
        "decision_type": {"type": "string", "enum": ["request_completion"]},
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
