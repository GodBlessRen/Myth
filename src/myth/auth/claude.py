"""Myth 自有 Claude OAuth 认证适配器。

使用 Anthropic user OAuth 的 authorization-code + PKCE S256；客户端身份由 Myth 配置，
不会复用 Claude Code / Anthropic CLI 的 client_id。access/refresh token 只进入系统安全凭据库，
.runtime/oauth/claude.json 仅保存非秘钥配置与公开账号元数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import base64
import hashlib
import json
import math
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
from .transport import open_credential_request, read_bounded, redact_response
from .state_lock import AuthStateLock
from ..network_recovery import ConnectionNotDispatched, is_pre_dispatch_disconnect


CONSOLE_URL = "https://platform.claude.com"
API_URL = "https://api.anthropic.com"
AUTHORIZATION_ENDPOINT = CONSOLE_URL + "/oauth/authorize"
TOKEN_ENDPOINT = API_URL + "/v1/oauth/token"
SCOPES = "user:profile user:inference user:developer"
OAUTH_BETA = "oauth-2025-04-20"
KEYRING_SERVICE = "Myth Claude OAuth"
REFRESH_SKEW_SECONDS = 300
LOGIN_TTL_SECONDS = 600


class ClaudeOAuthError(RuntimeError):
    """可公开的 Claude OAuth 错误；消息不得包含 code、verifier 或 token。"""


def _serialized_auth(method):
    """同根目录跨实例/进程串行；嵌套状态投影复用当前线程已经持有的锁。"""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        """实例内重入复用 OS 锁；同根其他实例必须重新取得锁并读取权威文件。"""
        with self._lock:
            if getattr(self._state_depth, "value", 0):
                return method(self, *args, **kwargs)
            with AuthStateLock(self.metadata_path.with_suffix(".lock"), self.timeout * 2 + 5,
                               ClaudeOAuthError("Claude authentication is busy; try again.")):
                self._state_depth.value = 1
                try:
                    return method(self, *args, **kwargs)
                finally:
                    self._state_depth.value = 0
    return wrapped


# Claude OAuth 的公开只读连接投影；字段来自配置/授权元数据，不携带任何秘钥。
@dataclass(frozen=True)
class ClaudeAuthStatus:
    # connected：当前根/客户端/授权代次存在非空 token；不证明刷新或模型请求成功。
    connected: bool
    # client_id_configured：Myth 自己的公开 OAuth 客户端身份已配置；不是秘钥。
    client_id_configured: bool
    # email：授权响应公开账号邮箱；仅用于 UI 标识。
    email: str | None = None
    # organization：授权响应公开组织名称/身份；不授予额外 Runtime 权限。
    organization: str | None = None
    # workspace：授权响应公开工作区名称/身份；不替代项目 scope。
    workspace: str | None = None
    # scopes：供应商实际返回的 OAuth scope；执行仍走 Runtime 准入。
    scopes: tuple[str, ...] = ()
    # expires_at：access token 的 Unix 到期时间；仅用于提前刷新。
    expires_at: float | None = None
    # login_revision：最近成功登录挑战身份；供浏览器轮询确认本次授权。
    login_revision: str | None = None
    # reason：未连接时的脱敏原因；不得包含 token/code/verifier。
    reason: str | None = None

    # 生成可返回 Web 的脱敏投影；不包含任何 access/refresh token。
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


def _public_fields(value: dict[str, Any], *credentials: dict[str, Any]) -> dict[str, Any]:
    """保留预期公开标量并移除已知秘密的字面回显；不声称检测任意编码。"""
    identities = {"client_id", "login_revision", "login_epoch", "challenge_revision"}
    safe = {key: value[key] for key in (*identities, "email", "organization", "workspace", "scope")
            if isinstance(value.get(key), str)}
    expires_at = value.get("expires_at")
    if type(expires_at) in {int, float} and math.isfinite(expires_at):
        safe["expires_at"] = expires_at
    if type(value.get("refresh_pending")) is bool:
        safe["refresh_pending"] = value["refresh_pending"]
    for credential in credentials:
        for key in ("access_token", "refresh_token", "id_token", "code", "code_verifier", "state"):
            secret = credential.get(key)
            if isinstance(secret, str) and secret:
                # 本地公开身份不是远端显示内容，不能用回显替换改写客户端/授权代次。
                safe = {key: item if key in identities else redact_response(item, secret)
                        for key, item in safe.items()}
    return safe


def _configured_client_id(metadata: dict[str, Any]) -> str:
    """配置与状态共用有效身份规则；环境变量只作显式部署后备。"""
    return str(metadata.get("client_id") or os.environ.get("MYTH_CLAUDE_OAUTH_CLIENT_ID") or "").strip()


class ClaudeOAuthManager:
    """认证生命周期所有者；同根 OS 锁串行修改，凭据按根目录隔离。

    挑战正文只在内存，公开文件保存授权代次、挑战代次和轮转待核对标记。
    文件、系统安全库与远端不是同一事务；失败关闭使用权，不能猜测远端已撤销。
    """

    # 装配公开元数据路径、安全凭据端口与进程内登录挑战；构造本身不访问远端。
    def __init__(
        self,
        root: str | Path,
        *,
        credential_store: CredentialStore | None = None,
        timeout: float = 30.0,
    ) -> None:
        # root：用户明确选择的 Myth 根目录；只保存非秘钥 OAuth 元数据。
        self.root = Path(root).resolve()
        # metadata_path：公开客户端/账号投影；严禁写 access/refresh token。
        self.metadata_path = self.root / ".runtime" / "oauth" / "claude.json"
        # profile_id：规范化根路径的公开摘要；使系统凭据槽与本机 OS 锁拥有相同作用域。
        self.profile_id = "root-" + hashlib.sha256(os.path.normcase(str(self.root)).encode("utf-8")).hexdigest()
        # credential_store：系统安全凭据端口；生产无明文文件降级。
        self.credential_store = credential_store or KeyringCredentialStore(KEYRING_SERVICE)
        # timeout：单次 OAuth 网络请求秒数上限；超时不泄露请求凭据。
        self.timeout = min(max(float(timeout), 1.0), 60.0)
        # _pending：当前进程的限时 PKCE/state 挑战；重启后旧挑战自然失效。
        self._pending: dict[str, dict[str, Any]] = {}
        # _lock：串行本实例登录/刷新/退出，防止同进程令牌轮换交叉覆盖。
        self._lock = threading.RLock()
        # _state_depth：当前线程的重入标记；不能替代其他实例的 OS 互斥。
        self._state_depth = threading.local()

    # 读取非秘钥 OAuth 元数据并校验形状；损坏时显式失败而不是猜测账号状态。
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

    # 原子发布预期标量和已知秘密脱敏投影；字段白名单不能证明字段内容安全。
    def _save_metadata(self, value: dict[str, Any], *credentials: dict[str, Any]) -> None:
        safe = _public_fields(value, *credentials)
        atomic_write(
            self.metadata_path,
            json.dumps(safe, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8"),
        )

    # 解析 Myth 自有 client_id；元数据优先，环境变量仅作显式部署配置。
    def _client_id(self) -> str:
        metadata = self._load_metadata()
        value = _configured_client_id(metadata)
        if not value:
            raise ClaudeOAuthError(
                "Claude OAuth client_id is not configured. Configure Myth's own OAuth client before signing in."
            )
        return value

    # 保存公开 client_id；切换客户端时清除旧客户端绑定的安全凭据。
    @_serialized_auth
    def configure(self, client_id: str) -> ClaudeAuthStatus:
        value = str(client_id or "").strip()
        if not 1 <= len(value) <= 200 or re.fullmatch(r"[A-Za-z0-9._:-]+", value) is None:
            raise ValueError("Claude OAuth client_id is invalid")
        with self._lock:
            metadata = self._load_metadata()
            previous = _configured_client_id(metadata)
            if previous != value:
                # 先失效旧挑战/授权；删除安全库失败时保留旧配置，不虚报切换成功。
                metadata["login_epoch"] = secrets.token_hex(16)
                self._pending.clear()
                metadata.pop("challenge_revision", None)
                metadata["refresh_pending"] = False
                self._save_metadata(metadata)
                self.credential_store.delete(self.profile_id)
                for key in ("email", "organization", "workspace", "scope", "expires_at", "login_revision"):
                    metadata.pop(key, None)
            metadata["client_id"] = value
            self._save_metadata(metadata)
            return self.status()

    # 从随机 verifier 计算 RFC 7636 S256 challenge；verifier 本身不持久化。
    @staticmethod
    def _pkce(verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    # 回调敏感字段必须恰好出现一次；重复参数拒绝而不择一猜测。
    @staticmethod
    def _single(query: dict[str, list[str]], name: str) -> str:
        values = query.get(name) or []
        if len(values) != 1 or not isinstance(values[0], str) or not values[0]:
            raise ClaudeOAuthError(f"OAuth callback is missing a valid {name}.")
        return values[0]

    # 只接受当前 Myth loopback Claude callback，防止 code 被转发到任意地址。
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

    # 创建一次性 PKCE/state 登录挑战并返回供应商授权 URL；不产生持久凭据。
    @_serialized_auth
    def begin_login(self, redirect_uri: str) -> dict[str, Any]:
        self._validate_redirect(redirect_uri)
        client_id = self._client_id()
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(32)
        login_id = secrets.token_hex(16)
        now = time.time()
        with self._lock:
            metadata = self._load_metadata()
            # 挑战代次独立于当前授权；打开/拒绝另一个登录页不能提前使现有账号失效。
            epoch = metadata.setdefault("login_epoch", secrets.token_hex(16))
            challenge_revision = secrets.token_hex(16)
            metadata["challenge_revision"] = challenge_revision
            self._save_metadata(metadata)
            self._pending = {
                state: {
                    "verifier": verifier,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "login_id": login_id,
                    "expires_at": now + LOGIN_TTL_SECONDS,
                    "login_epoch": epoch,
                    "challenge_revision": challenge_revision,
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

    # 用固定 token endpoint 交换 code；client_id/redirect/state 必须与原挑战完全一致。
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

    # 有界读取 token 响应并只暴露固定错误文本；远端正文不进入异常消息。
    def _read_token_response(self, req: request.Request, public_error: str) -> dict[str, Any]:
        try:
            with open_credential_request(req, timeout=self.timeout) as response:
                raw = read_bounded(response)
        except error.HTTPError as exc:
            exc.close()
            raise ClaudeOAuthError(public_error) from None
        except error.URLError as exc:
            if is_pre_dispatch_disconnect(exc.reason):
                # 仅 connect 适配器签发的证据能解除 refresh_pending；不保留远端错误正文。
                raise ConnectionNotDispatched() from None
            raise ClaudeOAuthError("Claude OAuth service is temporarily unavailable.") from None
        except ConnectionNotDispatched:
            raise
        except OSError:
            raise ClaudeOAuthError("Claude OAuth service is temporarily unavailable.") from None
        try:
            value = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ClaudeOAuthError("Claude OAuth returned malformed data.") from None
        if not isinstance(value, dict) or not isinstance(value.get("access_token"), str) or not value["access_token"]:
            raise ClaudeOAuthError("Claude OAuth did not return an access token.")
        return value

    # 消费一次性 state、交换 token 并分离保存秘钥与公开账号元数据。
    @_serialized_auth
    def complete_callback(self, query: dict[str, list[str]]) -> ClaudeAuthStatus:
        state = self._single(query, "state")
        denied = bool(query.get("error"))
        code = "" if denied else self._single(query, "code")
        with self._lock:
            pending = self._pending.pop(state, None)
            if pending is None or pending["expires_at"] <= time.time():
                raise ClaudeOAuthError("Claude OAuth state is unknown or expired.")
            metadata = self._load_metadata()
            if (pending["login_epoch"] != metadata.get("login_epoch")
                    or pending["challenge_revision"] != metadata.get("challenge_revision")
                    or pending["client_id"] != self._client_id()):
                raise ClaudeOAuthError("Claude OAuth challenge was invalidated; start sign-in again.")
            # 拒绝也消费自己的 state；无关 state 不能取消当前挑战，当前授权继续保留。
            if denied:
                raise ClaudeOAuthError("Claude authorization was denied.")
            previous_credential = self.credential_store.load(self.profile_id) or {}
            token = self._token_exchange(pending, code, state)
            # OS 锁只约束遵守协议的调用者；环境变量/文件被外部修改仍需在效果后复核。
            metadata = self._load_metadata()
            if (pending["login_epoch"] != metadata.get("login_epoch")
                    or pending["challenge_revision"] != metadata.get("challenge_revision")
                    or pending["client_id"] != self._client_id()):
                raise ClaudeOAuthError("Claude OAuth challenge was invalidated; start sign-in again.")
            callback_secrets = {"code": code, "code_verifier": pending["verifier"], "state": state}
            refresh = token.get("refresh_token")
            if not isinstance(refresh, str) or not refresh:
                raise ClaudeOAuthError("Claude OAuth did not return a refresh token.")
            expires_at = self._expires_at(token)
            scope = _public_fields({"scope": token.get("scope", SCOPES)},
                                   previous_credential, token, callback_secrets).get("scope", "")
            credential = {
                "access_token": token["access_token"],
                "refresh_token": refresh,
                "expires_at": expires_at,
                "scope": scope,
                "client_id": pending["client_id"],
                "login_epoch": pending["login_epoch"],
            }
            self.credential_store.save(self.profile_id, credential)
            organization = token.get("organization") if isinstance(token.get("organization"), dict) else {}
            account = token.get("account") if isinstance(token.get("account"), dict) else {}
            workspace = token.get("workspace") if isinstance(token.get("workspace"), dict) else {}
            metadata.update({
                "client_id": pending["client_id"],
                "email": account.get("email_address"),
                "organization": organization.get("name") or organization.get("uuid"),
                "workspace": workspace.get("name") or workspace.get("id"),
                "scope": scope,
                "expires_at": expires_at,
                "login_revision": pending["login_id"],
                "refresh_pending": False,
            })
            self._save_metadata(metadata, previous_credential, token, callback_secrets)
            return self.status()

    @staticmethod
    def _expires_at(token):
        """拒绝不可用的到期事实；缺测不授予无限期 access token 使用权。"""
        duration = token.get("expires_in")
        if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= 604800:
            raise ClaudeOAuthError("Claude OAuth returned an invalid token lifetime.")
        return time.time() + duration

    # 用 refresh token 和原 client_id 刷新；轮转前持久化 pending，未知结果不能重发旧凭据。
    def _refresh(self, credential: dict[str, Any]) -> dict[str, Any]:
        refresh = credential.get("refresh_token")
        client_id = credential["client_id"]
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
        metadata = self._load_metadata()
        metadata["refresh_pending"] = True
        self._save_metadata(metadata)
        try:
            token = self._read_token_response(req, "Claude OAuth refresh was rejected; sign in again.")
        except ConnectionNotDispatched:
            # 确认请求未发出才能解除占用；普通超时/拒绝/异常保留 pending，不能重放旧轮转。
            metadata = self._load_metadata()
            metadata["refresh_pending"] = False
            self._save_metadata(metadata, credential)
            # 向真实 Provider 保留固定零派发证据，才能让当前 Run 进入网络恢复而非认证终止。
            raise ConnectionNotDispatched() from None
        metadata = self._load_metadata()
        if client_id != self._client_id() or credential.get("login_epoch") != metadata.get("login_epoch"):
            raise ClaudeOAuthError("Claude OAuth local authorization changed; sign in again.")
        expires_at = self._expires_at(token)
        rotated = token.get("refresh_token", refresh)
        if not isinstance(rotated, str) or not rotated:
            raise ClaudeOAuthError("Claude OAuth returned an invalid refresh token; sign in again.")
        updated = {
            **credential,
            "access_token": token["access_token"],
            "refresh_token": rotated,
            "expires_at": expires_at,
            "scope": _public_fields({"scope": token.get("scope", credential.get("scope", ""))},
                                    credential, token).get("scope", ""),
            "client_id": client_id,
        }
        self.credential_store.save(self.profile_id, updated)
        metadata["expires_at"] = expires_at
        metadata["scope"] = updated["scope"]
        metadata["refresh_pending"] = False
        organization = token.get("organization") if isinstance(token.get("organization"), dict) else {}
        account = token.get("account") if isinstance(token.get("account"), dict) else {}
        workspace = token.get("workspace") if isinstance(token.get("workspace"), dict) else {}
        if account.get("email_address"):
            metadata["email"] = account["email_address"]
        if organization.get("name") or organization.get("uuid"):
            metadata["organization"] = organization.get("name") or organization.get("uuid")
        if workspace.get("name") or workspace.get("id"):
            metadata["workspace"] = workspace.get("name") or workspace.get("id")
        self._save_metadata(metadata, credential, token)
        return updated

    # 按到期窗口取得/刷新 access token；仅传给 Provider 调用边界。
    @_serialized_auth
    def access_token(self) -> str:
        with self._lock:
            credential = self.credential_store.load(self.profile_id)
            if not credential:
                raise ClaudeOAuthError("Claude is not signed in.")
            metadata = self._load_metadata()
            if metadata.get("refresh_pending"):
                raise ClaudeOAuthError("Claude OAuth refresh outcome is unresolved; sign in again.")
            if credential.get("client_id") != self._client_id():
                raise ClaudeOAuthError("Claude OAuth credential belongs to another client; sign in again.")
            if (not isinstance(metadata.get("login_epoch"), str) or not metadata["login_epoch"]
                    or credential.get("login_epoch") != metadata["login_epoch"]):
                raise ClaudeOAuthError("Claude OAuth local authorization was invalidated; sign in again.")
            expires_at = credential.get("expires_at")
            if (type(expires_at) not in {int, float} or not math.isfinite(expires_at)
                    or expires_at <= time.time() + REFRESH_SKEW_SECONDS):
                # 缺失/非有限到期事实也需建立有效轮转事实，不能解释成无限期使用权。
                credential = self._refresh(credential)
            token = credential.get("access_token")
            if not isinstance(token, str) or not token:
                raise ClaudeOAuthError("Claude access token is unavailable.")
            return token

    # 生成脱敏连接状态；安全凭据库不可用时报告原因而不降级到明文。
    @_serialized_auth
    def status(self) -> ClaudeAuthStatus:
        metadata = self._load_metadata()
        client_id = _configured_client_id(metadata)
        client_id_configured = bool(client_id)
        try:
            credential = self.credential_store.load(self.profile_id)
        except CredentialStoreUnavailable as exc:
            return ClaudeAuthStatus(False, client_id_configured, reason=str(exc))
        # 异源/被撤销的凭据不能冒充连接，旧账号展示与 scope 同时失效。
        if credential and credential.get("client_id") != client_id:
            return ClaudeAuthStatus(False, client_id_configured, reason="client_binding_mismatch")
        if credential and (not isinstance(metadata.get("login_epoch"), str) or not metadata["login_epoch"]
                           or credential.get("login_epoch") != metadata["login_epoch"]):
            return ClaudeAuthStatus(False, client_id_configured, reason="local_authorization_invalidated")
        token = (credential or {}).get("access_token")
        connected = bool(client_id_configured and isinstance(token, str) and token and not metadata.get("refresh_pending"))
        public = _public_fields({
            **metadata,
            # 安全库中的 None、0、空范围都是当前事实；旧文件投影不能覆盖缺测。
            "scope": credential.get("scope", "") if credential else metadata.get("scope", ""),
            "expires_at": credential.get("expires_at") if credential else metadata.get("expires_at"),
        }, credential or {})
        return ClaudeAuthStatus(
            connected,
            client_id_configured,
            email=public.get("email"),
            organization=public.get("organization"),
            workspace=public.get("workspace"),
            scopes=tuple(item for item in public.get("scope", "").split() if item),
            expires_at=public.get("expires_at"),
            login_revision=public.get("login_revision"),
            reason=None if connected else ("refresh_unresolved" if metadata.get("refresh_pending") else "not_configured" if not client_id_configured else "not_signed_in"),
        )

    # 清除 Myth 本机 OAuth 使用权和公开账号投影；不虚构供应商远端撤销结果。
    @_serialized_auth
    def logout(self) -> dict[str, Any]:
        with self._lock:
            # 退出意图先取消内存挑战；随后文件/安全库失败仍抛出，不能虚报 signed_out。
            self._pending.clear()
            metadata = self._load_metadata()
            metadata["login_epoch"] = secrets.token_hex(16)
            metadata.pop("challenge_revision", None)
            metadata["refresh_pending"] = False
            for key in ("email", "organization", "workspace", "scope", "expires_at", "login_revision"):
                metadata.pop(key, None)
            self._save_metadata(metadata)
            self.credential_store.delete(self.profile_id)
        return {"signed_out": True, "remote_revocation": "not_claimed"}
