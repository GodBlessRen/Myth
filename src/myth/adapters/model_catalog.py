"""公开模型价格目录适配器；只请求固定公共 URL，不接收凭据、消息或任意网络地址。"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import math
import threading
import time
from urllib.request import Request, urlopen

# 公开目录按提供方和精确模型 ID 匹配；不同计费渠道不能借模型同名互换。
CATALOG_URL = "https://models.dev/api.json"
PROVIDER_KEYS = {"openai": "openai", "anthropic": "anthropic", "deepseek": "deepseek", "kimi": "moonshotai"}
OFFICIAL_URLS = {
    "openai": "https://developers.openai.com/api/docs/pricing",
    "anthropic": "https://platform.claude.com/docs/en/about-claude/pricing",
    "deepseek": "https://api-docs.deepseek.com/quick_start/pricing",
    "kimi": "https://platform.kimi.ai/docs/pricing/chat",
}


def _download():
    """事务外有界下载公共 JSON；重定向后仍须来自固定目录站点。"""
    request = Request(CATALOG_URL, headers={"User-Agent": "Myth/public-model-catalog", "Accept": "application/json"})
    with urlopen(request, timeout=6) as response:
        if response.geturl() != CATALOG_URL:
            raise ValueError("model catalog redirected")
        data = response.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("model catalog is too large")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("invalid model catalog")
    return value


class PublicModelCatalog:
    """一小时公共内存缓存；查询失败保留明确标为过期的结果，不阻止离线工作。"""

    def __init__(self, loader=None):
        """初始化无业务状态的公共缓存；可注入离线夹具，网络不进入 Runtime 事务。"""
        # loader：可注入确定性公开目录替身；生产只使用上方固定 URL。
        self.loader = loader or _download
        # lock：串行刷新公共缓存，不与任何业务写事务组合。
        self.lock = threading.Lock()
        # data：上次成功查询的公开模型数据。
        self.data = {}
        # checked_at：上次成功查询的 UTC 时间。
        self.checked_at = None
        # refreshed：单调时钟控制成功缓存的一小时 TTL。
        self.refreshed = 0.0
        # attempted：单调时钟控制失败/强制刷新十秒节流。
        self.attempted = -10.0

    def info(self, provider, model, *, force=False):
        """返回精确匹配的标价和来源；零占位、未知模型、订阅/本地渠道均不伪造免费。"""
        if provider not in (*PROVIDER_KEYS, "ollama", "chatgpt", "claude_oauth") or not isinstance(model, str) or len(model) > 200:
            raise ValueError("invalid model catalog selection")
        if type(force) is not bool:
            raise ValueError("force must be a boolean")
        model = model.strip()
        result = {"provider": provider, "model": model, "pricing": None, "status": "unknown",
                  "checked_at": None, "stale": False, "source_url": CATALOG_URL,
                  "official_url": OFFICIAL_URLS.get("anthropic" if provider == "claude_oauth" else provider), "max_output_tokens": None}
        if not model:
            return {**result, "status": "unselected"}
        if provider in {"ollama", "chatgpt", "claude_oauth"}:
            status = "local_or_hosted" if provider == "ollama" else "subscription" if provider == "chatgpt" else "oauth_channel"
            return {**result, "status": status}
        with self.lock:
            now = time.monotonic()
            if (force or not self.data or now - self.refreshed >= 3600) and now - self.attempted >= 10:
                self.attempted = now
                try:
                    data = self.loader()
                    if not isinstance(data, dict):
                        raise ValueError("invalid model catalog")
                    self.data = data
                    self.refreshed = now
                    self.checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                except (OSError, ValueError, TypeError):
                    pass
            stale = not self.data or now - self.refreshed >= 3600
            channel = self.data.get(PROVIDER_KEYS[provider])
            models = channel.get("models") if isinstance(channel, dict) else None
            row = models.get(model) if isinstance(models, dict) else None
            result.update(checked_at=self.checked_at, stale=stale)
            if not isinstance(row, dict):
                return {**result, "status": "unavailable" if stale else "unknown"}
            cost = row.get("cost") if isinstance(row.get("cost"), dict) else {}
            rates = [cost.get("input"), cost.get("output")]
            limits = row.get("limit") if isinstance(row.get("limit"), dict) else {}
            limit = limits.get("output")
            if type(limit) is int and limit > 0:
                result["max_output_tokens"] = limit
            if any(type(x) not in {int, float} or not math.isfinite(x) or x < 0 or x > 100000 for x in rates) or not any(rates):
                return {**result, "status": "unpublished"}
            result.update(status="priced", pricing={"currency": "USD", "input": float(rates[0]),
                "output": float(rates[1]), "source": "models.dev", "provider": provider, "model": model,
                "checked_at": self.checked_at, "stale": stale})
            return result

    def quote_settings(self, settings):
        """在保存/准入前解析公开标价；自定义合同单价保持显式覆盖，执行快照不会中途更新。"""
        result = copy.deepcopy(settings)
        pool = result.setdefault("model_pool", {"enabled": True, "adaptive": True, "children": []})
        profiles = [(result, pool, "main_pricing")]
        profiles.extend((child, child, "pricing") for child in pool.get("children", []))
        for profile, owner, key in profiles:
            rates = owner.get(key)
            info = self.info(profile["provider"], profile.get("model", ""))
            ceiling = info.get("max_output_tokens")
            if ceiling and profile.get("max_output_tokens", 2048) > ceiling:
                raise ValueError(f"{profile.get('model')} 的输出 Token 上限为 {ceiling}")
            if rates and rates.get("source") != "models.dev":
                continue
            owner[key] = info["pricing"]
        return result
