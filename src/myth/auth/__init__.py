"""本应用独立认证包入口。
包导出本身不启动业务工作；具体状态归属、I/O 和恢复合同见被导出模块。"""

from .provider_keys import ProviderApiKeyVault, API_KEY_PROVIDERS
from .claude import ClaudeOAuthManager, ClaudeAuthStatus, ClaudeOAuthError
from .chatgpt import (
    ChatGPTAuthManager,
    ChatGPTAuthStatus,
    ChatGPTOAuthError,
    CredentialStoreUnavailable,
    run_loopback_login,
)

# __all__：当前公开入口；新增入口必须有实际调用方。
__all__ = [
    "ChatGPTAuthManager",
    "ChatGPTAuthStatus",
    "ChatGPTOAuthError",
    "CredentialStoreUnavailable",
    "run_loopback_login",
    "ClaudeOAuthManager",
    "ClaudeAuthStatus",
    "ClaudeOAuthError",
    "ProviderApiKeyVault",
    "API_KEY_PROVIDERS",
]
