"""同一冻结 State 下的 Context 四臂影子编译；只比较模型请求材料，不调用 Provider。

本模块是实验诊断，不是新的 Runtime/State Owner。影子编译不能写 Ticket/Receipt，
也不能把摘要差异解释为任务质量提升或 Provider 实际传输的第三方证明。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..domain import digest_json
from ..models import ModelRequest


# 唯一四臂定义：Benchmark 和影子编译消费同一不可变机制配置。
_COMMON = ("action_fusion", "context_compaction", "observation_recall")
CONTEXT_BENCHMARK_ARMS: dict[str, tuple[str, ...]] = {
    "context-baseline": _COMMON,
    "context-causal": _COMMON + ("context_causal_guard",),
    "context-relevance": _COMMON + ("context_relevance_ranking",),
    "context-full": _COMMON + ("context_causal_guard", "context_relevance_ranking"),
}
_MATERIAL_CONTRASTS = {
    "causal_without_relevance": ("context-baseline", "context-causal"),
    "causal_with_relevance": ("context-relevance", "context-full"),
    "relevance_without_causal": ("context-baseline", "context-relevance"),
    "relevance_with_causal": ("context-causal", "context-full"),
}


# 只摘要会进入 Provider 适配器的模型无关输入；context_report 是本地审计元数据，不是 Prompt。
def model_visible_digest(request: ModelRequest | Mapping[str, Any]) -> str:
    value = request.serializable() if isinstance(request, ModelRequest) else dict(request)
    if not isinstance(value.get("messages"), list) and not isinstance(request, ModelRequest):
        raise ValueError("model-visible request messages are missing")
    if not isinstance(value.get("model"), str):
        raise ValueError("model-visible request model is missing")
    return digest_json({key: item for key, item in value.items() if key != "context_report"})


# 四次编译只替换两种 Context 开关，其他 State/Settings/Activities/控制快照全部相同。
# 未能编译任一反事实时返回 UNVERIFIED，不阻断原有生产模型机会，也不补造零开销。
def frozen_context_material_probe(
    current_request: ModelRequest,
    mechanisms: object,
    recompile: Callable[[tuple[str, ...]], ModelRequest],
) -> dict[str, Any] | None:
    if (
        not isinstance(mechanisms, (tuple, list))
        or not all(isinstance(item, str) for item in mechanisms)
        or len(set(mechanisms)) != len(mechanisms)
    ):
        return None
    arm = next(
        (name for name, configured in CONTEXT_BENCHMARK_ARMS.items()
         if set(configured) == set(mechanisms)),
        None,
    )
    if arm is None:
        return None
    try:
        actual_digest = model_visible_digest(current_request)
        variants = {
            name: model_visible_digest(recompile(configured))
            for name, configured in CONTEXT_BENCHMARK_ARMS.items()
        }
    except Exception as exc:
        # 只记录类型不记录异常正文（可能包含 Prompt/路径/私密来源）。
        return {
            "method": "frozen-state-4arm-request-material-v1",
            "status": "UNVERIFIED",
            "reason": "shadow_compilation_failed",
            "exception_type": type(exc).__name__,
            "current_arm": arm,
        }
    if variants[arm] != actual_digest:
        return {
            "method": "frozen-state-4arm-request-material-v1",
            "status": "UNVERIFIED",
            "reason": "current_request_differs_from_shadow",
            "current_arm": arm,
        }
    return {
        "method": "frozen-state-4arm-request-material-v1",
        "status": "FROZEN_COMPILER_MEASURED",
        "current_arm": arm,
        "actual_visible_digest": actual_digest,
        "variant_visible_digests": variants,
        "material_contrasts": {
            name: variants[before] != variants[after]
            for name, (before, after) in _MATERIAL_CONTRASTS.items()
        },
        "provider_wire_verified": False,
        "causal_attribution": False,
    }
