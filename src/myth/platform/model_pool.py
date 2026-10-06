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
PROVIDERS = ("ollama", "openai", "chatgpt", "deepseek", "anthropic", "claude_oauth", "kimi")
TASK_TYPES = ("general", "extract", "summarize", "code", "reason", "review")
DIFFICULTIES = {"easy": 1, "medium": 2, "hard": 3}


def pricing(value):
    """价格以每百万 Token 的指定币种计；留空为未配置，禁止 NaN/负数。"""
    if value is None or value == {}:
        return None
    metadata = {"source", "provider", "model", "checked_at", "stale"}
    if not isinstance(value, dict) or set(value) - {"currency", "input", "output"} - metadata:
        raise ValueError("价格字段无效")
    currency = value.get("currency", "USD")
    if currency not in {"USD", "CNY"}:
        raise ValueError("价格币种必须为 USD 或 CNY")
    result = {"currency": currency}
    for key in ("input", "output"):
        rate = value.get(key)
        if type(rate) not in {int, float} or not math.isfinite(rate) or not 0 <= rate <= 100000:
            raise ValueError("输入与输出单价必须同时填写有限非负数")
        result[key] = float(rate)
    if value.get("source") is not None:
        if value["source"] != "models.dev" or value.get("provider") not in PROVIDERS:
            raise ValueError("自动价格来源无效")
        for key in ("model", "checked_at"):
            if not isinstance(value.get(key), str) or not 1 <= len(value[key]) <= 200:
                raise ValueError("自动价格来源缺少模型或查询时间")
        if type(value.get("stale")) is not bool:
            raise ValueError("自动价格须标明缓存是否过期")
        result.update({key: value[key] for key in metadata})
    elif set(value) & metadata:
        raise ValueError("手动价格不能混入自动来源字段")
    return result


def pricing_identity(settings):
    """入口去重不绑定公共标价的刷新时间；显式合同费率仍属于用户配置身份。"""
    import copy
    result = copy.deepcopy(settings)
    pool = result.get("model_pool")
    if isinstance(pool, dict):
        for owner, key in [(pool, "main_pricing"), *((child, "pricing") for child in pool.get("children", []))]:
            rates = owner.get(key)
            if rates and rates.get("source") == "models.dev":
                owner[key] = None
    return result


def clean_pool(value):
    """只保存公开白名单配置；每轮准入沿用设置快照，不读取执行中途的新配置。"""
    # 池与槽位分别校验公开字段白名单，凭据不进入设置快照。
    # 槽位身份、模型、上下文、输出和步数均有界；供应商相关窗口/温度约束在准入前确定。
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
               "ollama_url", "num_ctx", "thinking", "temperature", "pricing", "max_steps"}
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
        ceiling = 1 if provider in {"anthropic", "claude_oauth"} else 2
        if type(temperature) not in {int, float} or not 0 <= temperature <= ceiling:
            raise ValueError(f"子模型采样温度须为 0–{ceiling}")
        steps = item.get("max_steps", 4)
        if type(steps) is not int or not 1 <= steps <= 8:
            raise ValueError("子任务步骤上限须为 1–8")
        label = item.get("label", pid)
        if not isinstance(label, str) or len(label) > 80:
            raise ValueError("invalid child label")
        result["children"].append({"id": pid, "label": label, "provider": provider, "model": model.strip(),
            "tier": tier, "enabled": enabled, "task_types": list(dict.fromkeys(categories)),
            "max_output_tokens": tokens, "ollama_url": endpoint.rstrip("/"), "num_ctx": window,
            "thinking": normalize_thinking(item.get("thinking")), "temperature": float(temperature),
            "pricing": pricing(item.get("pricing")), "max_steps": steps})
    return result


def profile_key(profile):
    """经验绑定模型和生成配置；换模型/窗口/推理配置后不沿用旧能力评分。"""
    identity = {k: profile.get(k) for k in ("provider", "model", "thinking", "num_ctx", "temperature", "max_output_tokens", "effective_output_tokens")}
    identity["prompt_version"] = "isolated-worker-v2"
    identity["max_steps"] = profile.get("max_steps", 4)
    if profile.get("provider") == "ollama":
        identity["ollama_url"] = profile.get("ollama_url")
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]


def route(pool, task_type, difficulty, history, unavailable=(), preferred_profile_id=None):
    """档位是初始先验；主模型可明确选槽位，质量反馈校准同类能力并避开拒收结果。"""
    # 先按冻结槽位的配置身份筛同类最近经验，再排除禁用、不可用和近期质量失败。
    # 评分只校准能力档位；明确槽位偏好仍经过排除规则，无合格槽位返回父模型回退。
    if task_type not in TASK_TYPES or difficulty not in DIFFICULTIES:
        raise ValueError("任务类别或难度无效")
    required = DIFFICULTIES[difficulty]
    candidates, excluded, experience = [], [], []
    if preferred_profile_id is not None and preferred_profile_id not in {p["id"] for p in pool.get("children", [])}:
        raise ValueError("主模型所选槽位不在冻结模型池中")
    for profile in pool.get("children", []):
        key = profile_key(profile)
        samples = [x for x in history if x.get("profile_key") == key and x.get("task_type") == task_type
                   and x.get("failure_kind") in {"quality", "none"}][:5]
        similar = [x for x in samples if DIFFICULTIES.get(x.get("difficulty"), 3) <= required]
        reason = None
        if not pool.get("enabled", True) or not profile["enabled"]:
            reason = "disabled"
        elif profile["id"] in unavailable:
            reason = "unavailable_in_this_run"
        elif profile["task_types"] and task_type not in profile["task_types"]:
            reason = "task_type_mismatch"
        elif pool.get("adaptive", True) and similar and (not similar[0]["accepted"] or similar[0]["score"] < 70):
            reason = "recent_quality_failure"
        effective_tier = samples[0].get("capability_tier", profile["tier"]) if samples and pool.get("adaptive", True) else profile["tier"]
        experience.append({"profile_id": profile["id"], "initial_tier": profile["tier"],
            "effective_tier": effective_tier, "samples": len(samples),
            "latest_score": samples[0]["score"] if samples else None})
        if not reason and effective_tier < required and profile["id"] != preferred_profile_id:
            reason = "below_initial_or_learned_tier"
        if reason:
            excluded.append({"profile_id": profile["id"], "reason": reason})
        else:
            candidates.append((effective_tier, profile))
    candidates.sort(key=lambda p: (p[0], p[1]["id"]))
    selected = next((p for _, p in candidates if p["id"] == preferred_profile_id), None) if preferred_profile_id else (candidates[0][1] if candidates else None)
    return {"policy_version": "pool-v2", "task_type": task_type, "difficulty": difficulty,
            "required_tier": required, "profile": selected, "excluded": excluded,
            "reason": ("main_selected" if preferred_profile_id else "initial_or_reviewed_capability") if selected else "parent_fallback",
            "experience": experience,
            "history_samples": len(history)}


def delegated_results(activities):
    """按父步骤与批次 ordinal 展开交接；单项与并行项共享审核、替代和上下文规则。"""
    return [child for x in activities for child in
            ((x.get("result") or {}).get("results") or [x.get("result") or {}])]


def pending_resolutions(activities):
    """拒收结果必须由主模型提供替代内容，或被已接受的新委派取代；花销仍保留。"""
    results = delegated_results(activities)
    resolved = {r["resolution"]["delegation_id"] for r in results if r.get("resolution")}
    accepted = {r["review"]["delegation_id"] for r in results if r.get("review", {}).get("accepted")}
    resolved.update(r.get("handoff", {}).get("replaces") for r in results if r.get("delegation_id") in accepted)
    return [r["review"]["delegation_id"] for r in results if r.get("review")
            and not r["review"]["accepted"] and r["review"]["delegation_id"] not in resolved]


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
    results = delegated_results(activities)
    reviews = {x.get("review", {}).get("delegation_id") for x in results}
    return [x["delegation_id"] for x in results if x.get("review_required")
            and x["delegation_id"] not in reviews]
