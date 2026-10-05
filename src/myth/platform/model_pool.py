"""模型池的纯配置、路由与计价合同。

主模型提出任务类别/难度，路由仅在用户配置的三个子槽位内选择。评分是有来源的
主模型意见，不等同独立验收；自适应只调整同类任务偏好，不修改权限或策略代码。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from urllib.parse import urlparse

from ..model_capabilities import normalize_thinking

# 提供方、类别和等级是配置合同；品牌名称不构成能力排名。
PROVIDERS = ("ollama", "openai", "chatgpt", "deepseek", "anthropic", "kimi")
TASK_TYPES = ("general", "extract", "summarize", "code", "reason", "review")
DIFFICULTIES = {"easy": 1, "medium": 2, "hard": 3}


def pricing(value):
    """价格以每百万 Token 的指定币种计；留空为未配置，禁止 NaN/负数。"""
    if value is None or value == {}:
        return None
    if not isinstance(value, dict) or set(value) - {"currency", "input", "output"}:
        raise ValueError("价格只允许 currency/input/output")
    currency = value.get("currency", "USD")
    if currency not in {"USD", "CNY"}:
        raise ValueError("价格币种必须为 USD 或 CNY")
    result = {"currency": currency}
    for key in ("input", "output"):
        rate = value.get(key)
        if type(rate) not in {int, float} or not math.isfinite(rate) or not 0 <= rate <= 100000:
            raise ValueError("输入与输出单价必须同时填写有限非负数")
        result[key] = float(rate)
    return result


def clean_pool(value):
    """只保存公开白名单配置；每轮准入沿用设置快照，不读取执行中途的新配置。"""
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - {"enabled", "adaptive", "children", "main_pricing"}:
        raise ValueError("invalid model pool fields")
    children = value.get("children", [])
    if not isinstance(children, list) or len(children) > 3:
        raise ValueError("模型池最多配置 3 个子模型")
    result = {"enabled": value.get("enabled", True), "adaptive": value.get("adaptive", True),
              "main_pricing": pricing(value.get("main_pricing")), "children": []}
    if type(result["enabled"]) is not bool or type(result["adaptive"]) is not bool:
        raise ValueError("模型池开关必须为布尔值")
    ids = set()
    allowed = {"id", "label", "provider", "model", "tier", "enabled", "task_types", "max_output_tokens",
               "ollama_url", "num_ctx", "thinking", "temperature", "pricing"}
    for item in children:
        if not isinstance(item, dict) or set(item) - allowed:
            raise ValueError("invalid child model fields; credentials belong in the vault")
        pid = item.get("id", "")
        if not isinstance(pid, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", pid) or pid in ids:
            raise ValueError("子模型槽位 ID 必须唯一")
        ids.add(pid)
        provider, model = item.get("provider"), item.get("model", "")
        if provider not in PROVIDERS or not isinstance(model, str) or not 1 <= len(model.strip()) <= 200:
            raise ValueError("子模型提供方或模型名称无效")
        tier, enabled = item.get("tier", 1), item.get("enabled", True)
        if type(tier) is not int or tier not in {1, 2, 3} or type(enabled) is not bool:
            raise ValueError("子模型能力等级必须为 1–3")
        categories = item.get("task_types", [])
        if not isinstance(categories, list) or any(x not in TASK_TYPES for x in categories):
            raise ValueError("unsupported task type")
        endpoint = item.get("ollama_url", "http://127.0.0.1:11434")
        if not isinstance(endpoint, str):
            raise ValueError("invalid local endpoint")
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or any(
            (parsed.username, parsed.password, parsed.query, parsed.fragment)
        ):
            raise ValueError("invalid local endpoint")
        tokens, window = item.get("max_output_tokens", 2048), item.get("num_ctx", 8192)
        if type(tokens) is not int or not 128 <= tokens <= 32768:
            raise ValueError("子模型输出上限须为 128–32768 Token")
        if type(window) is not int or not 2048 <= window <= 262144 or (provider == "ollama" and window <= tokens + 512):
            raise ValueError("子模型上下文不足")
        temperature = item.get("temperature", 0.0)
        if type(temperature) not in {int, float} or not 0 <= temperature <= 2:
            raise ValueError("invalid child temperature")
        label = item.get("label", pid)
        if not isinstance(label, str) or len(label) > 80:
            raise ValueError("invalid child label")
        result["children"].append({"id": pid, "label": label, "provider": provider, "model": model.strip(),
            "tier": tier, "enabled": enabled, "task_types": list(dict.fromkeys(categories)),
            "max_output_tokens": tokens, "ollama_url": endpoint.rstrip("/"), "num_ctx": window,
            "thinking": normalize_thinking(item.get("thinking")), "temperature": float(temperature),
            "pricing": pricing(item.get("pricing"))})
    return result


def profile_key(profile):
    """经验绑定模型和生成配置；换模型/窗口/推理配置后不沿用旧能力评分。"""
    identity = {k: profile.get(k) for k in ("provider", "model", "thinking", "num_ctx", "temperature", "max_output_tokens", "effective_output_tokens")}
    identity["prompt_version"] = "isolated-worker-v1"
    if profile.get("provider") == "ollama":
        identity["ollama_url"] = profile.get("ollama_url")
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]


def route(pool, task_type, difficulty, history, unavailable=()):
    """先满足能力下限，再按近期同类反馈避开失败配置；没有可选子模型交回主模型。"""
    if task_type not in TASK_TYPES or difficulty not in DIFFICULTIES:
        raise ValueError("任务类别或难度无效")
    required = DIFFICULTIES[difficulty]
    candidates, excluded = [], []
    for profile in pool.get("children", []):
        key = profile_key(profile)
        samples = [x for x in history if x.get("profile_key") == key and x.get("task_type") == task_type
                   and x.get("difficulty") == difficulty and x.get("failure_kind") in {"quality", "none"}][:5]
        reason = None
        if not pool.get("enabled", True) or not profile["enabled"]:
            reason = "disabled"
        elif profile["id"] in unavailable:
            reason = "unavailable_in_this_run"
        elif profile["tier"] < required:
            reason = "below_required_tier"
        elif profile["task_types"] and task_type not in profile["task_types"]:
            reason = "task_type_mismatch"
        elif pool.get("adaptive", True) and samples and (not samples[0]["accepted"] or samples[0]["score"] < 70):
            reason = "recent_quality_failure"
        if reason:
            excluded.append({"profile_id": profile["id"], "reason": reason})
        else:
            candidates.append(profile)
    # 最新同类失败抬高下限；不把小模型品牌或单次网络故障当成能力结论。
    failed_tiers = [p["tier"] for p in pool.get("children", [])
                    if any(x["profile_id"] == p["id"] and x["reason"] == "recent_quality_failure" for x in excluded)]
    if failed_tiers:
        required = max(required, max(failed_tiers) + 1)
    excluded.extend({"profile_id": p["id"], "reason": "below_learned_tier"} for p in candidates if p["tier"] < required)
    candidates = [p for p in candidates if p["tier"] >= required]
    candidates.sort(key=lambda p: (p["tier"], p["id"]))
    selected = candidates[0] if candidates else None
    return {"policy_version": "pool-v1", "task_type": task_type, "difficulty": difficulty,
            "required_tier": required, "profile": selected, "excluded": excluded,
            "reason": "lowest_sufficient_tier" if selected else "parent_fallback",
            "history_samples": len(history)}


def estimate_cost(usage, rates):
    """按配置标价估算金额，不冒充账单；缓存折扣未计，任一 Token 缺测保持未知。"""
    tokens = [usage.get(k) for k in ("input_tokens", "output_tokens")]
    amount = None
    if rates and all(type(x) is int and x >= 0 for x in tokens):
        amount = round((tokens[0] * rates["input"] + tokens[1] * rates["output"]) / 1_000_000, 9)
    return {"amount": amount, "currency": rates["currency"] if rates else None,
            "basis": "configured_list_price", "cache_discount_included": False, "pricing": rates}


def pending_reviews(activities):
    """从已消费工具事实计算尚未评分的子任务，避免凭模型文字宣称已评审。"""
    reviews = {(x.get("result") or {}).get("review", {}).get("delegation_id") for x in activities}
    return [x["decision_id"] for x in activities if (x.get("result") or {}).get("review_required")
            and x.get("decision_id") not in reviews]
