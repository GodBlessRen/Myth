"""远端模型 API Key 的应用内安全凭据中心。
浏览器只提交一次明文到 loopback 服务；凭据仅进入操作系统安全凭据库，Runtime SQLite、事件、Artifact 和 Web 状态都只保存脱敏状态。
"""

from __future__ import annotations

import os
from typing import Any

from .chatgpt import KeyringCredentialStore, CredentialStoreUnavailable


# 当前真正使用 API Key 的 Provider；新增远端 Provider 时必须显式加入，避免任意字符串创建系统凭据记录。
API_KEY_PROVIDERS = {
    "openai": {"label": "OpenAI", "env_var": "OPENAI_API_KEY"},
    "deepseek": {"label": "DeepSeek", "env_var": "DEEPSEEK_API_KEY"},
}
# API_KEY_SERVICE：与 ChatGPT OAuth 分开的系统凭据命名空间；API Key 不与 OAuth token 共用记录。
API_KEY_SERVICE = "Myth Provider API Keys"


class ProviderApiKeyVault:
    """应用内 API Key 深模块；调用方只关心 save/delete/resolve/status，不知道 keyring 分块实现。"""

    # 构造只保存系统凭据适配器；真正读写发生在用户连接或 Provider 调用边界。
    def __init__(self, store=None) -> None:
        # store：系统安全凭据端口；只拥有 API Key 秘钥字节，Runtime/Workspace 不取得读取权。
        self.store = store or KeyringCredentialStore(service=API_KEY_SERVICE)

    # Provider 名必须属于实际适配器白名单；不能用前端文本扩大系统凭据命名空间。
    @staticmethod
    def _spec(provider: str) -> dict[str, str]:
        value = API_KEY_PROVIDERS.get(str(provider).strip().lower())
        if value is None:
            raise ValueError("provider does not use a Myth-managed API key")
        return value

    # 校验用户粘贴的 API Key 形状；不记录、不回显、不尝试推断厂商前缀。
    @staticmethod
    def _clean_secret(secret: Any) -> str:
        if not isinstance(secret, str):
            raise ValueError("API key must be text")
        value = secret.strip()
        if not 8 <= len(value) <= 8192:
            raise ValueError("API key length is invalid")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise ValueError("API key contains control characters")
        return value

    # 在任何网络验证前只做本地形状校验；返回值仅限同一次服务调用使用，不能写日志或 Web 状态。
    def prepare(self, provider: str, secret: Any) -> str:
        self._spec(str(provider).strip().lower())
        return self._clean_secret(secret)

    # 保存到系统凭据库；记录只含 provider + key，不进入项目根或 Runtime 数据库。
    def save(self, provider: str, secret: str) -> dict[str, Any]:
        provider_id = str(provider).strip().lower()
        spec = self._spec(provider_id)
        value = self.prepare(provider_id, secret)
        self.store.save(
            provider_id,
            {"kind": "api_key", "provider": provider_id, "api_key": value},
        )
        return {
            "provider": provider_id,
            "label": spec["label"],
            "configured": True,
            "source": "myth",
        }

    # 删除 Myth 自己保存的 key；环境变量兼容值属于进程外配置，不能由页面删除。
    def delete(self, provider: str) -> dict[str, Any]:
        provider_id = str(provider).strip().lower()
        spec = self._spec(provider_id)
        self.store.delete(provider_id)
        env_ready = bool(os.environ.get(spec["env_var"], "").strip())
        return {
            "provider": provider_id,
            "label": spec["label"],
            "configured": env_ready,
            "source": "environment" if env_ready else None,
        }

    # 从 Myth 安全库优先读取，旧环境变量仅作为兼容回退；返回 source 供 UI/观测解释，不泄露 key。
    def resolve(self, provider: str) -> tuple[str, str]:
        provider_id = str(provider).strip().lower()
        spec = self._spec(provider_id)
        try:
            stored = self.store.load(provider_id)
        except CredentialStoreUnavailable:
            stored = None
        if isinstance(stored, dict):
            if stored.get("kind") != "api_key" or stored.get("provider") != provider_id:
                raise CredentialStoreUnavailable("Stored provider credential has an invalid shape.")
            value = stored.get("api_key")
            if isinstance(value, str) and value:
                return value, "myth"
        env_value = os.environ.get(spec["env_var"], "").strip()
        if env_value:
            return env_value, "environment"
        raise CredentialStoreUnavailable(
            f"{spec['label']} API key is not connected in Myth."
        )

    # 只返回是否已连接以及来源；任何异常都转成可公开 reason，绝不返回 key 或其片段。
    def status(self, provider: str) -> dict[str, Any]:
        provider_id = str(provider).strip().lower()
        spec = self._spec(provider_id)
        try:
            _, source = self.resolve(provider_id)
            return {
                "provider": provider_id,
                "label": spec["label"],
                "configured": True,
                "source": source,
                "reason": None,
            }
        except CredentialStoreUnavailable as exc:
            return {
                "provider": provider_id,
                "label": spec["label"],
                "configured": False,
                "source": None,
                "reason": str(exc),
            }

    # 设置页一次取得全部 API Key Provider 的脱敏状态；顺序固定便于前端稳定渲染。
    def statuses(self) -> list[dict[str, Any]]:
        return [self.status(provider) for provider in API_KEY_PROVIDERS]


__all__ = [
    "API_KEY_PROVIDERS",
    "ProviderApiKeyVault",
    "CredentialStoreUnavailable",
]
