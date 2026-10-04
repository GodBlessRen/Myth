"""本应用独立认证包入口。
包导出本身不启动业务工作；具体状态归属、I/O 和恢复合同见被导出模块。"""

from .provider_keys import ProviderApiKeyVault, API_KEY_PROVIDERS
from .chatgpt import (
    ChatGPTAuthManager,
    ChatGPTAuthStatus,
    ChatGPTOAuthError,
    CredentialStoreUnavailable,
    run_loopback_login,
)

# __all__：公开导出名单；兼容别名只有在确认外部迁移完成后才删除。
__all__ = [
    "ChatGPTAuthManager",
    "ChatGPTAuthStatus",
    "ChatGPTOAuthError",
    "CredentialStoreUnavailable",
    "run_loopback_login",
    "ProviderApiKeyVault",
    "API_KEY_PROVIDERS",
]
