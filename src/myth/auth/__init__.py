"""Authentication adapters owned by Myth.

OAuth credentials are deliberately outside Runtime SQLite/events/object storage.
"""

from .chatgpt import (
    ChatGPTAuthManager,
    ChatGPTAuthStatus,
    ChatGPTOAuthError,
    CredentialStoreUnavailable,
    run_loopback_login,
)

__all__ = [
    "ChatGPTAuthManager",
    "ChatGPTAuthStatus",
    "ChatGPTOAuthError",
    "CredentialStoreUnavailable",
    "run_loopback_login",
]
