"""模型能力目录的供应商无关投影。
Core 只理解能力形状和安全输入，不定义任何厂商的 reasoning 档位；具体 levels/default/off 来自远端目录或 Provider adapter。
"""

from __future__ import annotations

import re
from typing import Any


# _SETTING_TOKEN：控制值只允许短标识，阻止自由文本借设置字段进入供应商请求。
_SETTING_TOKEN = re.compile(r"^[a-z][a-z0-9_.-]{0,31}$")


# 构造 reasoning 能力投影；levels/off/default 保持 Provider 原生值，不做跨厂商语义映射。
def reasoning_capability(
    *,
    kind: str,
    levels: list[str] | tuple[str, ...] = (),
    default: str | None = None,
    off: str | bool | None = None,
    source: str = "provider",
) -> dict[str, Any]:
    clean_levels = [
        str(value).strip().lower()
        for value in levels
        if isinstance(value, str) and _SETTING_TOKEN.fullmatch(value.strip().lower())
    ]
    clean_default = (
        str(default).strip().lower()
        if isinstance(default, str)
        and _SETTING_TOKEN.fullmatch(default.strip().lower())
        else None
    )
    clean_off: str | bool | None = off
    if isinstance(off, str):
        value = off.strip().lower()
        clean_off = value if _SETTING_TOKEN.fullmatch(value) else None
    return {
        "kind": str(kind),
        "levels": clean_levels,
        "default": clean_default,
        "off": clean_off,
        "source": str(source),
    }


# 构造单模型公开能力；未知字段保持 None/空列表，不能用猜测冒充远端事实。
def model_capability(
    model_id: str,
    *,
    display_name: str | None = None,
    context_window: int | None = None,
    max_output_tokens: int | None = None,
    input_modalities: list[str] | tuple[str, ...] = (),
    output_modalities: list[str] | tuple[str, ...] = (),
    reasoning: dict[str, Any] | None = None,
    provider_metadata: dict[str, Any] | None = None,
    source: str = "provider",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": str(model_id),
        "display_name": str(display_name or model_id),
        "source": str(source),
        "input_modalities": [str(value) for value in input_modalities if isinstance(value, str)],
        "output_modalities": [str(value) for value in output_modalities if isinstance(value, str)],
    }
    if type(context_window) is int and context_window > 0:
        result["context_window"] = context_window
    if type(max_output_tokens) is int and max_output_tokens > 0:
        result["max_output_tokens"] = max_output_tokens
    if reasoning is not None:
        result["reasoning"] = dict(reasoning)
    if isinstance(provider_metadata, dict):
        # provider_metadata：目录中的厂商特有公开字段；只用于折叠展示/分析，不改变 Core 能力语义。
        result["provider_metadata"] = dict(provider_metadata)
    return result


# 从公开 details 取得所选模型能力；缺目录或缺模型时返回 None，不自行推断。
def selected_model_capability(
    details: dict[str, Any] | None, model_id: str | None
) -> dict[str, Any] | None:
    if not isinstance(details, dict) or not model_id:
        return None
    profiles = details.get("model_capabilities")
    if not isinstance(profiles, dict):
        return None
    value = profiles.get(str(model_id))
    return dict(value) if isinstance(value, dict) else None


# 归一化用户显式 reasoning 选择；只处理 default/on/off 兼容词，其余原生档位原样保留给 Provider。
def normalize_thinking(value: Any) -> str | bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        raise ValueError("Thinking 必须选择模型原生档位，不能填写数字")
    token = str(value).strip().lower()
    if not token or token == "default":
        return None
    if token in {"on", "true"}:
        return True
    if token in {"off", "false"}:
        return False
    if not _SETTING_TOKEN.fullmatch(token):
        raise ValueError("thinking must be a short provider-native option")
    return token


# 核对动态目录中可证明的模型/输出上限；未知能力不伪造限制，reasoning 由 Provider 最终解释。
def validate_model_selection(
    settings: dict[str, Any], details: dict[str, Any] | None
) -> None:
    # 目录没有事实就不臆造限制；有能力声明时才核对原生输出与 Thinking 选项。
    if not isinstance(details, dict):
        return
    model = str(settings.get("model") or "").strip()
    models = details.get("models")
    if model and isinstance(models, list) and models and model not in models:
        raise ValueError("所选模型不在当前 Provider 返回的可用目录中。")
    profile = selected_model_capability(details, model)
    if not profile:
        return
    ceiling = profile.get("max_output_tokens")
    requested = settings.get("max_output_tokens")
    if (
        type(ceiling) is int
        and ceiling > 0
        and type(requested) is int
        and requested > ceiling
    ):
        raise ValueError(f"每步输出 Token 超过该模型上限 {ceiling}。")
    reasoning = profile.get("reasoning") if isinstance(profile.get("reasoning"), dict) else None
    thinking = normalize_thinking(settings.get("thinking"))
    if reasoning is None:
        if thinking is not None:
            raise ValueError("当前模型未声明可调 Thinking；请使用 Provider 默认行为。")
        return
    if thinking is None:
        return
    if isinstance(thinking, bool):
        if reasoning.get("kind") in {"toggle", "boolean"} or thinking is reasoning.get("off") or (thinking is False and reasoning.get("off") is not None):
            return
        raise ValueError("当前模型使用推理档位；请选择其原生选项")
    allowed = {
        str(value)
        for value in (reasoning.get("levels") or [])
        if isinstance(value, str)
    }
    off = reasoning.get("off")
    if isinstance(off, str):
        allowed.add(off)
    if thinking not in allowed:
        raise ValueError(
            "当前模型不支持所选 Thinking 档位；请按模型能力重新选择。"
        )
