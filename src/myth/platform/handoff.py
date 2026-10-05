"""主子交接的纯表示合同。

信封身份和计量来自 Runtime，正文与摘要来自子模型；默认投影有界，完整对象按
摘要回读。元数据采信、内容采用和已发生花销分别表达，模型不能回写供应商收据。
"""

from __future__ import annotations

from .completion import CompletionVerdict
from ..failures import FailureObservation


# 返回元数据可包含厂商新增统计；凭据、正文、私有思维和请求输入不进入此投影。
_PRIVATE = {"authorization", "headers", "request_headers", "response_headers", "cookie", "cookies",
    "set-cookie", "api_key", "access_token", "refresh_token", "id_token", "encrypted_content",
    "reasoning_text", "reasoning_content", "thinking", "text", "content", "output", "choices",
    "messages", "input", "request", "request_body", "x-api-key", "token", "secret", "password", "client_secret"}


def public_metadata(value):
    """完整保留公开供应商字段及未知统计；脱敏后持久保存，上下文由回读分页限制。"""
    if isinstance(value, dict):
        return {str(k): public_metadata(v) for k, v in value.items()
                if str(k).lower() not in _PRIVATE}
    if isinstance(value, list):
        return [public_metadata(v) for v in value]
    if isinstance(value, str):
        return value
    return value if value is None or type(value) in {int, float, bool} else None


def project_handoffs(activities):
    """拒收正文从默认上下文移除，保留身份、评分与花销；显式回读仍可检查原结果。"""
    reviews = {(x.get("result") or {}).get("review", {}).get("delegation_id"):
               (x.get("result") or {}).get("review") for x in activities}
    def project(result):
        """拒收只改变默认投影，批次中每一项保持原 identity/ordinal/费用。"""
        result = dict(result)
        review = reviews.get(result.get("delegation_id"))
        if result.get("handoff"):
            result["adoption"] = "accepted" if review and review["accepted"] else "rejected" if review else "pending_review"
            if review and not review["accepted"]:
                result["summary"] = "主模型已拒收此结果；使用 agent.result 按需核对原文，后续结论应基于替代结果。"
                result["coverage"] = ""
                result["evidence_refs"] = []
                result["remaining"] = []
        return result
    projected = []
    for activity in activities:
        result = project(activity.get("result") or {})
        if "results" in result:
            result["results"] = [parallel_brief(project(child)) for child in result["results"]]
        projected.append({**activity, "result": result})
    return projected


def parallel_brief(result):
    """批次默认导航有界；完整摘要/正文/元数据留在原子收据与对象，裁剪明确标注。"""
    if not result.get("handoff"):
        return result
    brief = {k: result[k] for k in ("delegation_id", "ordinal", "adoption", "review_required", "fallback_to_parent") if k in result}
    brief.update({"summary": result.get("summary", "")[:300], "summary_kind": result.get("summary_kind"),
        "summary_truncated": len(result.get("summary", "")) > 300,
        "status": (result.get("subagent") or {}).get("status"),
        "coverage": result.get("coverage", "")[:200], "remaining": result.get("remaining", [])[:3],
        "evidence_refs": result.get("evidence_refs", [])[:3],
        "details_truncated": len(result.get("remaining", [])) > 3 or len(result.get("evidence_refs", [])) > 3,
        "handoff": {k: result["handoff"].get(k) for k in ("content_ref", "content_chars", "metadata_digest", "depends_on", "replaces")},
        "usage": {k: v for k, v in (result.get("telemetry", {}).get("usage") or {}).items()
                  if k in {"model_calls", "input_tokens", "output_tokens", "provider_wall_ms", "cached_tokens", "reasoning_tokens"}},
        "cost": {k: v for k, v in (result.get("telemetry", {}).get("cost") or {}).items()
                 if k in {"amount", "currency", "basis"}},
        "profile_id": (result.get("routing", {}).get("profile") or {}).get("id"),
        "read_capability": "agent.result"})
    return brief


class SubagentCompletionGuard:
    """子流程可返回部分完成与缺口；本地只核对输出界限和已委派来源，不伪造主评分。"""

    def __init__(self, source_refs):
        """冻结来源集合；新引用只能来自本次显式输入，不能引用父级未分享的资料。"""
        # source_refs：已准入的来源身份集合。
        self.source_refs = set(source_refs)

    def evaluate(self, turn, decision):
        """复用共同应用循环的完成策略入口，允许 remaining 交回主模型处理。"""
        message = None
        if any(x not in self.source_refs for x in decision.evidence_refs):
            message = "子任务返回了未委派的来源，请只引用已有 source_refs。"
        elif len(decision.summary or "") > 1200 or len((decision.claim or "").encode()) > 1_000_000:
            message = "结果超出交接合同：摘要最多 1200 字符，正文最多 1 MB。"
        if message:
            return CompletionVerdict(False, FailureObservation("verification", "handoff_contract", message, True))
        return CompletionVerdict(True)
