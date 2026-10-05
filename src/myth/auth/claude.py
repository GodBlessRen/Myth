"""Myth 自有 Claude OAuth 认证适配器。

使用 Anthropic user OAuth 的 authorization-code + PKCE S256；客户端身份由 Myth 配置，
不会复用 Claude Code / Anthropic CLI 的 client_id。access/refresh token 只进入系统安全凭据库，
.runtime/oauth/claude.json 仅保存非秘钥配置与公开账号元数据。
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Any
from urllib import error, parse, request

from ..artifacts import atomic_write
from .chatgpt import CredentialStore, KeyringCredentialStore, CredentialStoreUnavailable
from .transport import open_credential_request, read_bounded


CONSOLE_URL = "https://platform.claude.com"
API_URL = "https://api.anthropic.com"
AUTHORIZATION_ENDPOINT = CONSOLE_URL + "/oauth/authorize"
TOKEN_ENDPOINT = API_URL + "/v1/oauth/token"
SCOPES = "user:profile user:inference user:developer"
OAUTH_BETA = "oauth-2025-04-20"
KEYRING_SERVICE = "Myth Claude OAuth"
PROFILE_ID = "default"
REFRESH_SKEW_SECONDS = 300
LOGIN_TTL_SECONDS = 600


class ClaudeOAuthError(RuntimeError):
    """可公开的 Claude OAuth 错误；消息不得包含 code、verifier 或 token。"""


@dataclass(frozen=True)
class ClaudeAuthStatus:
    connected: bool
    client_id_configured: bool
    email: str | None = None
    organization: str | None = None
    workspace: str | None = None
    scopes: tuple[str, ...] = ()
    expires_at: float | None = None
    login_revision: str | None = None
    reason: str | None = None

    def serializable(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "client_id_configured": self.client_id_configured,
            "email": self.email,
            "organization": self.organization,
            "workspace": self.workspace,
            "scopes": list(self.scopes),
            "expires_at": self.expires_at,
            "login_revision": self.login_revision,
            "reason": self.reason,
        }


class ClaudeOAuthManager:
    """Claude OAuth 生命周期所有者；挑战只在内存，token 只在 OS credential store。"""

    def __init__(
        self,
        root: str | Path,
        *,
        credential_store: CredentialStore | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.root = Path(root).resolve()
        self.metadata_path = self.root / ".runtime" / "oauth" / "claude.json"
        self.credential_store = credential_store or KeyringCredentialStore(KEYRING_SERVICE)
        self.timeout = min(max(float(timeout), 1.0), 60.0)
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def _load_metadata(self) -> dict[str, Any]:
        if not self.metadata_path.exists():
            return {}
        try:
            value = json.loads(self.metadata_path.read_text("utf-8"))
        except Exception:
            raise ClaudeOAuthError("Claude OAuth metadata is unreadable.") from None
        if not isinstance(value, dict):
            raise ClaudeOAuthError("Claude OAuth metadata has an invalid shape.")
        return value

    def _save_metadata(self, value: dict[str, Any]) -> None:
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        safe = {
            key: value[key]
            for key in (
                "client_id", "email", "organization", "workspace", "scope",
                "expires_at", "login_revision"
            )
            if key in value and value[key] is not None
        }
        atomic_write(
            self.metadata_path,
            json.dumps(safe, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        )

    def _client_id(self) -> str:
        metadata = self._load_metadata()
        value = str(metadata.get("client_id") or os.environ.get("MYTH_CLAUDE_OAUTH_CLIENT_ID") or "").strip()
        if not value:
            raise ClaudeOAuthError(
                "Claude OAuth client_id is not configured. Configure Myth's own OAuth client before signing in."
            )
        return value

    def configure(self, client_id: str) -> ClaudeAuthStatus:
        value = str(client_id or "").strip()
        if not 1 <= len(value) <= 200 or re.fullmatch(r"[A-Za-z0-9._:-]+", value) is None:
            raise ValueError("Claude OAuth client_id is invalid")
        with self._lock:
            metadata = self._load_metadata()
            if metadata.get("client_id") and metadata["client_id"] != value:
                # 更换客户端会使既有 refresh token 的绑定失效；先清除旧凭据，不能静默混用。
                self.credential_store.delete(PROFILE_ID)
                for key in ("email", "organization", "workspace", "scope", "expires_at", "login_revision"):
                    metadata.pop(key, None)
            metadata["client_id"] = value
            self._save_metadata(metadata)
            return self.status()

    @staticmethod
    def _pkce(verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    @staticmethod
    def _single(query: dict[str, list[str]], name: str) -> str:
        values = query.get(name) or []
        if len(values) != 1 or not isinstance(values[0], str):
            raise ClaudeOAuthError(f"OAuth callback is missing a valid {name}.")
        return values[0]

    @staticmethod
    def _validate_redirect(redirect_uri: str) -> None:
        parsed = parse.urlparse(redirect_uri)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or parsed.path != "/auth/claude/callback"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Claude OAuth redirect must be the exact Myth loopback callback")

    def begin_login(self, redirect_uri: str) -> dict[str, Any]:
        self._validate_redirect(redirect_uri)
        client_id = self._client_id()
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(32)
        login_id = secrets.token_hex(16)
        now = time.time()
        with self._lock:
            self._pending = {
                state: {
                    "verifier": verifier,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "login_id": login_id,
                    "expires_at": now + LOGIN_TTL_SECONDS,
                }
            }
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "code_challenge": self._pkce(verifier),
            "code_challenge_method": "S256",
        }
        return {
            "auth_url": AUTHORIZATION_ENDPOINT + "?" + parse.urlencode(params),
            "login_id": login_id,
            "expires_at": now + LOGIN_TTL_SECONDS,
        }

    def _token_exchange(self, pending: dict[str, Any], code: str, state: str) -> dict[str, Any]:
        body = parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": pending["verifier"],
            "client_id": pending["client_id"],
            "redirect_uri": pending["redirect_uri"],
            "state": state,
        }).encode("ascii")
        req = request.Request(
            TOKEN_ENDPOINT,
            data=body,
            method="POST",
            headers={"content-type": "application/x-www-form-urlencoded", "accept": "application/json"},
        )
        return self._read_token_response(req, "Claude OAuth authorization was rejected.")

    def _read_token_response(self, req: request.Request, public_error: str) -> dict[str, Any]:
        try:
            with open_credential_request(req, timeout=self.timeout) as response:
                raw = read_bounded(response)
        except error.HTTPError as exc:
            exc.close()
            raise ClaudeOAuthError(public_error) from None
        except (error.URLError, OSError):
            raise ClaudeOAuthError("Claude OAuth service is temporarily unavailable.") from None
        try:
            value = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ClaudeOAuthError("Claude OAuth returned malformed data.") from None
        if not isinstance(value, dict) or not isinstance(value.get("access_token"), str) or not value["access_token"]:
            raise ClaudeOAuthError("Claude OAuth did not return an access token.")
        return value

    def complete_callback(self, query: dict[str, list[str]]) -> ClaudeAuthStatus:
        if query.get("error"):
            raise ClaudeOAuthError("Claude authorization was denied.")
        state = self._single(query, "state")
        code = self._single(query, "code")
        with self._lock:
            pending = self._pending.pop(state, None)
            if pending is None or pending["expires_at"] < time.time():
                raise ClaudeOAuthError("Claude OAuth state is unknown or expired.")
            token = self._token_exchange(pending, code, state)
            refresh = token.get("refresh_token")
            if not isinstance(refresh, str) or not refresh:
                raise ClaudeOAuthError("Claude OAuth did not return a refresh token.")
            expires_in = token.get("expires_in")
            expires_at = time.time() + float(expires_in) if isinstance(expires_in, (int, float)) and expires_in > 0 else None
            scope = str(token.get("scope") or SCOPES)
            credential = {
                "access_token": token["access_token"],
                "refresh_token": refresh,
                "expires_at": expires_at,
                "scope": scope,
                "client_id": pending["client_id"],
            }
            self.credential_store.save(PROFILE_ID, credential)
            organization = token.get("organization") if isinstance(token.get("organization"), dict) else {}
            account = token.get("account") if isinstance(token.get("account"), dict) else {}
            workspace = token.get("workspace") if isinstance(token.get("workspace"), dict) else {}
            metadata = self._load_metadata()
            metadata.update({
                "client_id": pending["client_id"],
                "email": account.get("email_address"),
                "organization": organization.get("name") or organization.get("uuid"),
                "workspace": workspace.get("name") or workspace.get("id"),
                "scope": scope,
                "expires_at": expires_at,
                "login_revision": pending["login_id"],
            })
            self._save_metadata(metadata)
            return self.status()

    def _refresh(self, credential: dict[str, Any]) -> dict[str, Any]:
        refresh = credential.get("refresh_token")
        client_id = credential.get("client_id") or self._client_id()
        if not isinstance(refresh, str) or not refresh:
            raise ClaudeOAuthError("Claude OAuth refresh token is unavailable; sign in again.")
        body = json.dumps({
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
        }).encode("utf-8")
        req = request.Request(
            TOKEN_ENDPOINT,
            data=body,
            method="POST",
            headers={
                "content-type": "application/json",
                "accept": "application/json",
                "anthropic-beta": OAUTH_BETA,
            },
        )
        token = self._read_token_response(req, "Claude OAuth refresh was rejected; sign in again.")
        expires_in = token.get("expires_in")
        expires_at = time.time() + float(expires_in) if isinstance(expires_in, (int, float)) and expires_in > 0 else None
        updated = {
            **credential,
            "access_token": token["access_token"],
            "refresh_token": token.get("refresh_token") or refresh,
            "expires_at": expires_at,
            "scope": str(token.get("scope") or credential.get("scope") or SCOPES),
            "client_id": client_id,
        }
        self.credential_store.save(PROFILE_ID, updated)
        metadata = self._load_metadata()
        metadata["expires_at"] = expires_at
        metadata["scope"] = updated["scope"]
        organization = token.get("organization") if isinstance(token.get("organization"), dict) else {}
        account = token.get("account") if isinstance(token.get("account"), dict) else {}
        workspace = token.get("workspace") if isinstance(token.get("workspace"), dict) else {}
        if account.get("email_address"):
            metadata["email"] = account["email_address"]
        if organization.get("name") or organization.get("uuid"):
            metadata["organization"] = organization.get("name") or organization.get("uuid")
        if workspace.get("name") or workspace.get("id"):
            metadata["workspace"] = workspace.get("name") or workspace.get("id")
        self._save_metadata(metadata)
        return updated

    def access_token(self) -> str:
        with self._lock:
            credential = self.credential_store.load(PROFILE_ID)
            if not credential:
                raise ClaudeOAuthError("Claude is not signed in.")
            expires_at = credential.get("expires_at")
            if isinstance(expires_at, (int, float)) and expires_at <= time.time() + REFRESH_SKEW_SECONDS:
                credential = self._refresh(credential)
            token = credential.get("access_token")
            if not isinstance(token, str) or not token:
                raise ClaudeOAuthError("Claude access token is unavailable.")
            return token

    def status(self) -> ClaudeAuthStatus:
        metadata = self._load_metadata()
        client_id_configured = bool(metadata.get("client_id") or os.environ.get("MYTH_CLAUDE_OAUTH_CLIENT_ID"))
        try:
            credential = self.credential_store.load(PROFILE_ID)
        except CredentialStoreUnavailable as exc:
            return ClaudeAuthStatus(False, client_id_configured, reason=str(exc))
        connected = bool(credential and credential.get("access_token"))
        scope = str((credential or {}).get("scope") or metadata.get("scope") or "")
        return ClaudeAuthStatus(
            connected,
            client_id_configured,
            email=metadata.get("email"),
            organization=metadata.get("organization"),
            workspace=metadata.get("workspace"),
            scopes=tuple(item for item in scope.split() if item),
            expires_at=(credential or {}).get("expires_at") or metadata.get("expires_at"),
            login_revision=metadata.get("login_revision"),
            reason=None if connected else ("not_configured" if not client_id_configured else "not_signed_in"),
        )

    def logout(self) -> dict[str, Any]:
        with self._lock:
            self.credential_store.delete(PROFILE_ID)
            metadata = self._load_metadata()
            for key in ("email", "organization", "workspace", "scope", "expires_at", "login_revision"):
                metadata.pop(key, None)
            self._pending.clear()
            self._save_metadata(metadata)
        return {"signed_out": True, "remote_revocation": "not_claimed"}
