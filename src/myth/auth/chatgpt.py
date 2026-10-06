"""Myth 自有 ChatGPT OAuth 的认证适配器。
PKCE/state/nonce/OIDC 校验与刷新串行化在此完成；token 只进系统凭据库，元数据不含秘钥。退出先关闭本机使用权，再尝试远端撤销并清理系统凭据。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Protocol
from urllib import error, parse, request
import uuid
import webbrowser

import jwt
import keyring
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from keyring.errors import PasswordDeleteError

from .. import __version__
from ..artifacts import atomic_write
from .transport import open_credential_request, read_bounded, public_error_code, redact_response
from .state_lock import AuthStateLock


# ISSUER：固定 OIDC 颁发者；验证 issuer 时必须精确匹配。
ISSUER = "https://auth.openai.com"
# AUTHORIZATION_ENDPOINT：固定登录授权入口；不能由模型输出替换。
AUTHORIZATION_ENDPOINT = f"{ISSUER}/api/accounts/authorize"
# TOKEN_ENDPOINT：固定凭据交换/刷新入口；请求内容属于认证边界。
TOKEN_ENDPOINT = f"{ISSUER}/api/accounts/oauth/token"
# REVOCATION_ENDPOINT：固定远端撤销入口；请求失败时保持未确认事实。
REVOCATION_ENDPOINT = f"{ISSUER}/api/accounts/oauth/revoke"
# JWKS_URL：固定签名公钥目录；签名验证不可省略。
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
# RESOURCE：本应用明确请求的资源受众；已授予 scope 仍须单独核对。
RESOURCE = "https://api.openai.com/v1"
# DYNAMIC_CLIENT_ID：动态注册流程的指定入口身份；不复用其他应用 client_id。
DYNAMIC_CLIENT_ID = "dynamic_agent_client"
# SCOPES：本应用请求的 OAuth 权限集合；请求不代表服务已授予。
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
# AGENT_NAME：注册使用的应用名称；不作为认证证据。
AGENT_NAME = "Myth"
# KEYRING_SERVICE：系统秘钥库命名空间；凭据不写 Runtime SQLite。
KEYRING_SERVICE = "Myth ChatGPT OAuth"
# REFRESH_SKEW_SECONDS：到期前提前刷新窗口，单位秒；刷新按线程/进程串行。
REFRESH_SKEW_SECONDS = 300
# LOGIN_TTL_SECONDS：登录挑战有效时长，单位秒；到期挑战不能交换凭据。
LOGIN_TTL_SECONDS = 600
# 进程内模型目录缓存只保存公开 slug/name；账号、登录/退出代次隔离，三十秒后重新查询。
_MODEL_CATALOG_CACHE: dict[tuple, tuple[float, tuple]] = {}
# 不同 Runtime 根的目录缓存写入锁；不能替代认证 state.lock。
_MODEL_CATALOG_LOCK = threading.Lock()

# _TERMINAL_REFRESH_ERRORS：明确不可继续刷新的拒绝码；标记重新授权，不无限重发。
_TERMINAL_REFRESH_ERRORS = {
    "invalid_grant",
    "invalid_refresh_token",
    "token_expired",
    "refresh_token_expired",
    "refresh_token_invalidated",
    "refresh_token_reused",
}


class ChatGPTOAuthError(RuntimeError):
    """可公开的脱敏认证错误；不得把 code/verifier/token 包入消息。"""


# 认证服务的明确拒绝；只携带错误分类和 HTTP 状态，不保存原始秘钥请求。
class OAuthRejected(ChatGPTOAuthError):
    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        # code：脱敏 OAuth/业务错误码；不携带原始远端错误描述或 token。
        self.code = code
        # status：公开 HTTP/服务状态值；不是模型调用成功的证明。
        self.status = status


# 系统安全凭据库不可用；拒绝降级到明文文件。
class CredentialStoreUnavailable(ChatGPTOAuthError):
    pass


# 认证秘钥存储端口；profile_id 定位凭据，元数据和 Runtime 数据库不取得秘钥写入权。
class CredentialStore(Protocol):
    # 按 profile_id 读取系统秘钥库并校验 JSON 形状；错误脱敏，不向 Runtime 返回原始秘钥。
    def load(self, profile_id: str) -> dict[str, Any] | None: ...

    # 把认证秘钥仅写系统凭据库；元数据路径和 Runtime DB 不参与保存。
    def save(self, profile_id: str, value: dict[str, Any]) -> None: ...

    # 清理指定 profile 的系统秘钥；不存在可幂等忽略，其他存储错误显式失败。
    def delete(self, profile_id: str) -> None: ...


class KeyringCredentialStore:
    """系统凭据库适配器；只接受直接选择的安全后端，失败时关闭认证能力。"""

    # 保存本应用系统秘钥库命名空间；实际访问前验证后端安全性，失败不明文降级。
    def __init__(self, service: str = KEYRING_SERVICE) -> None:
        # service：系统凭据库命名空间；不同合成测试必须使用随机独立名称。
        self.service = service

    # 选择可证明为直接安全系统存储的 keyring 后端；不可用时拒绝明文/链式降级。
    @staticmethod
    def _backend():
        backend = keyring.get_keyring()
        identity = f"{type(backend).__module__}.{type(backend).__name__}".lower()
        priority = getattr(backend, "priority", 0)
        try:
            numeric_priority = float(priority)
        except (TypeError, ValueError):
            numeric_priority = 0.0
        # 只接受 keyring 自带系统适配器的准确模块，不能凭类名包含 windows 等字样获得信任。
        secure_backend = type(backend).__module__ in {
            "keyring.backends.Windows", "keyring.backends.macOS",
            "keyring.backends.SecretService", "keyring.backends.kwallet",
            "keyring.backends.libsecret",
        }
        if (
            numeric_priority <= 0
            or not secure_backend
            or "fail" in identity
            or "plaintext" in identity
            or "null" in identity
            or "chainer" in identity
        ):
            raise CredentialStoreUnavailable(
                "No directly selected secure OS credential store is available. "
                "Configure Windows Credential Manager, macOS Keychain, Secret Service, or KWallet explicitly."
            )
        return backend

    # 每个 profile 独立服务名，避免 Windows 后端以共享 service 搬移其他账号的记录。
    def _record_service(self, profile_id: str) -> str:
        return f"{self.service}:record:{profile_id}"

    # 分块地址只由系统库内受校验的代次和序号构造，不能引用任意用户凭据。
    def _part_service(self, profile_id: str, generation: str, index: int) -> str:
        return f"{self.service}:part:{profile_id}:{generation}:{index}"

    # 读取系统库内的分块清单；清单先于块发布，崩溃后仍可枚举并删除未提交的代次。
    def _manifest(self, backend, profile_id: str) -> dict | None:
        raw = backend.get_password(self._record_service(profile_id), profile_id)
        if raw is None:
            return None
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("format") != "myth-credential-v2":
            raise ValueError("invalid manifest")
        entries = value.get("entries")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 4:
            raise ValueError("invalid manifest entries")
        generations = set()
        for entry in entries:
            if (not isinstance(entry, dict)
                    or re.fullmatch(r"[0-9a-f]{32}", str(entry.get("generation"))) is None
                    or re.fullmatch(r"[0-9a-f]{64}", str(entry.get("digest"))) is None
                    or type(entry.get("parts")) is not int or not 1 <= entry["parts"] <= 66
                    or entry["generation"] in generations):
                raise ValueError("invalid manifest entry")
            generations.add(entry["generation"])
        if value.get("active") is not None and value["active"] not in generations:
            raise ValueError("invalid manifest active generation")
        return value

    # 清单本身小于 Windows 单条上限，且没有 token 内容；所有字段仍在系统凭据库中。
    def _save_manifest(self, backend, profile_id: str, manifest: dict) -> None:
        backend.set_password(self._record_service(profile_id), profile_id,
            json.dumps(manifest, ensure_ascii=True, separators=(",", ":")))

    # 幂等删除系统记录；只吞不存在，其他错误保留清单供稍后再次清理。
    @staticmethod
    def _delete_record(backend, service: str, profile_id: str) -> None:
        try:
            backend.delete_password(service, profile_id)
        except PasswordDeleteError:
            pass

    # 删除清单的一整个代次；失败时调用方不能把该代次从清单静默移除。
    def _delete_generation(self, backend, profile_id: str, entry: dict) -> None:
        for index in range(entry["parts"]):
            self._delete_record(backend, self._part_service(profile_id, entry["generation"], index), profile_id)

    # 按 profile_id 读取系统秘钥库并校验 JSON 形状；错误脱敏，不向 Runtime 返回原始秘钥。
    def load(self, profile_id: str) -> dict[str, Any] | None:
        # 先从系统安全库核对活动代次、完整块和摘要，不能读取半发布的凭据。
        try:
            backend = self._backend()
            manifest = self._manifest(backend, profile_id)
            if manifest is None:
                return None
            active = manifest.get("active")
            if active is None:
                return None
            entry = next(item for item in manifest["entries"] if item["generation"] == active)
            pieces = [backend.get_password(self._part_service(profile_id, active, index), profile_id)
                for index in range(entry["parts"])]
            if not all(isinstance(piece, str) for piece in pieces):
                raise ValueError("credential generation is incomplete")
            raw = "".join(pieces)
            if hashlib.sha256(raw.encode("ascii")).hexdigest() != entry["digest"]:
                raise ValueError("credential generation digest mismatch")
        except CredentialStoreUnavailable:
            raise
        except Exception as exc:
            raise CredentialStoreUnavailable(
                "The OS credential store could not be read."
            ) from None
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CredentialStoreUnavailable(
                "Stored ChatGPT credentials are unreadable."
            ) from None
        if not isinstance(value, dict):
            raise CredentialStoreUnavailable(
                "Stored ChatGPT credentials have an invalid shape."
            )
        return value

    # 把认证秘钥仅写系统凭据库；元数据路径和 Runtime DB 不参与保存。
    def save(self, profile_id: str, value: dict[str, Any]) -> None:
        try:
            backend = self._backend()
            encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
            if len(encoded) > 65536:
                raise ValueError("credential record exceeds the byte limit")
            prior = self._manifest(backend, profile_id)
            entries = list(prior["entries"]) if prior else []
            if len(entries) >= 4:
                raise ValueError("credential cleanup is required before another save")
            generation = uuid.uuid4().hex
            pieces = [encoded[index:index + 1000] for index in range(0, len(encoded), 1000)]
            entry = {"generation": generation, "parts": len(pieces),
                "digest": hashlib.sha256(encoded.encode("ascii")).hexdigest()}
            manifest = {"format": "myth-credential-v2", "active": prior.get("active") if prior else None,
                "entries": entries + [entry]}
            # 先记录代次再写块；active 指针最后才切换，部分写入不能被 load 当作完整凭据。
            self._save_manifest(backend, profile_id, manifest)
            for index, piece in enumerate(pieces):
                backend.set_password(self._part_service(profile_id, generation, index), profile_id, piece)
            manifest["active"] = generation
            self._save_manifest(backend, profile_id, manifest)
            remaining = [entry]
            for old in entries:
                try:
                    self._delete_generation(backend, profile_id, old)
                except Exception:
                    remaining.append(old)
            manifest["entries"] = remaining
            self._save_manifest(backend, profile_id, manifest)
        except CredentialStoreUnavailable:
            raise
        except Exception as exc:
            raise CredentialStoreUnavailable(
                "The OS credential store could not save ChatGPT credentials."
            ) from None

    # 清理指定 profile 的系统秘钥；不存在可幂等忽略，其他存储错误显式失败。
    def delete(self, profile_id: str) -> None:
        try:
            backend = self._backend()
            manifest = self._manifest(backend, profile_id)
            if manifest is not None:
                for entry in manifest["entries"]:
                    self._delete_generation(backend, profile_id, entry)
                self._delete_record(backend, self._record_service(profile_id), profile_id)
        except CredentialStoreUnavailable:
            raise
        except Exception as exc:
            raise CredentialStoreUnavailable(
                "The OS credential store could not delete ChatGPT credentials."
            ) from None


# 内存中的单次登录挑战；state/nonce/verifier 有期限，不能序列化进 Runtime 或公开日志。
@dataclass(frozen=True)
class PendingLogin:
    # state：单次 OAuth 回调的随机匹配凭据；内存目录消费一次，不能记录到日志或业务数据库。
    state: str
    # nonce：本次 OIDC 防重放值；签名验证后仍须匹配此挑战。
    nonce: str
    # code_verifier：单次 PKCE 秘钥；只用于 code 交换，不进日志/Runtime。
    code_verifier: str
    # redirect_uri：固定 loopback callback；校验主机/路径后用于授权交换。
    redirect_uri: str
    # requested_client_id：本次注册/重授权客户端身份；不复用其他应用 client。
    requested_client_id: str
    # profile_id：本机明确账号配置身份；只用于定位系统凭据，不含 token。
    profile_id: str | None
    # created_at：挑战创建的 UTC epoch 秒；与 LOGIN_TTL_SECONDS 一起计算有效期。
    created_at: float
    # login_epoch：开始登录时固定的退出代次；跨管理器退出后，旧挑战不能重新连接账号。
    login_epoch: str
    # login_id：前端匹配本次已完成登录的非凭据身份；不能用旧 connected 状态冒充完成。
    login_id: str


# 对外认证状态投影；可见账号和到期信息，但不包含 access/refresh/ID token。
@dataclass(frozen=True)
class ChatGPTAuthStatus:
    # connected：当前认证/服务连接投影；不证明任何业务效果已完成。
    connected: bool
    # sharing：是否已授予 ChatGPT 计划使用权限；身份连接与计划授权分开。
    sharing: bool
    # ready：当前服务/后端可用性声明；不证明任务成功。
    ready: bool
    # profile_id：本机明确账号配置身份；只用于定位系统凭据，不含 token。
    profile_id: str | None
    # email：已验证账号的可公开邮箱投影；不是认证秘钥。
    email: str | None
    # name：用户/组件可见名称；不是稳定身份。
    name: str | None
    # expires_at：认证挑战/凭据到期的 UTC epoch 秒；按当前时间核对，不能无限复用。
    expires_at: int | None
    # scopes：服务实际授予的权限集合，不能由需求字符串假定获得。
    scopes: tuple[str, ...]
    # reason：可解释的选择/拒绝原因；不是授权证据。
    reason: str | None = None
    # login_revision：最近成功登录的公开机会身份；不含 OAuth state/nonce/token。
    login_revision: str | None = None

    # 生成 JSON 可保存的数据投影；保留身份、版本和单位，不在此授予执行或发布权限。
    def serializable(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "sharing": self.sharing,
            "ready": self.ready,
            "profile_id": self.profile_id,
            "email": self.email,
            "name": self.name,
            "expires_at": self.expires_at,
            "scopes": list(self.scopes),
            "reason": self.reason,
            "login_revision": self.login_revision,
        }


# 同一认证聚合只允许一个修改者；嵌套调用复用当前线程已经取得的 OS 锁。
def _serialized_auth(method):
    # 首次取得跨进程锁；finally 清深度，异常不能留下假锁所有权。
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._state_lock:
            if getattr(self._state_depth, "value", 0):
                return method(self, *args, **kwargs)
            with AuthStateLock(self.auth_dir / "state.lock", self.timeout * 2 + 5,
                               ChatGPTOAuthError("ChatGPT authentication is busy; try again.")):
                self._state_depth.value = 1
                try:
                    return method(self, *args, **kwargs)
                finally:
                    self._state_depth.value = 0
    return wrapped


# 认证装配与生命周期所有者；内存挑战、非秘钥元数据、系统秘钥库分开，修改跨线程/进程串行化。
class ChatGPTAuthManager:
    # 装配系统秘钥库端口、无 token 元数据路径、内存挑战及刷新锁；构造不自动登录/刷新，网络等待上限单位秒。
    def __init__(
        self,
        root: str | Path,
        *,
        credential_store: CredentialStore | None = None,
        timeout: float = 30.0,
    ) -> None:
        # root：已明确选择的根目录；具体读写仍由对应受限适配器校验。
        self.root = Path(root).resolve()
        # auth_dir：本机认证非秘钥元数据目录；与 Runtime 状态分离。
        self.auth_dir = self.root / ".runtime" / "oauth"
        # metadata_path：不含 token 的认证注册/选择元数据文件；与系统秘钥库不构成跨系统事务。
        self.metadata_path = self.auth_dir / "chatgpt.json"
        # timeout：一次网络/操作等待的上限，单位秒；超时不能证明远端未执行。
        self.timeout = timeout
        # credentials：系统安全凭据存储端口；不允许自动降级为明文文件。
        self.credentials = credential_store or KeyringCredentialStore()
        # _pending：仅存内存的登录挑战目录；单次 state 消费后删除，重启不恢复。
        self._pending: dict[str, PendingLogin] = {}
        # _pending_lock：登录挑战目录的线程锁；消费 state 与取得挑战在同一临界区。
        self._pending_lock = threading.Lock()
        # _state_lock：认证聚合可重入线程锁；所有生命周期修改共用 state.lock。
        self._state_lock = threading.RLock()
        # _state_depth：每线程嵌套深度；只能复用该线程持有的 OS 锁。
        self._state_depth = threading.local()
        # _jwks：固定身份服务的签名公钥客户端；验证 ID token 时使用，token 不写入 Runtime。
        self._jwks = jwt.PyJWKClient(JWKS_URL, timeout=timeout)
        self.auth_dir.mkdir(parents=True, exist_ok=True)

    # 生成去 padding 的 URL-safe Base64，供 PKCE challenge 与挑战身份使用。
    @staticmethod
    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    # 从系统随机源生成单次挑战；nbytes 为随机字节数，不能改用可预测 UUID。
    @staticmethod
    def _new_secret(nbytes: int = 32) -> str:
        return (
            base64.urlsafe_b64encode(secrets.token_bytes(nbytes))
            .rstrip(b"=")
            .decode("ascii")
        )

    # 读取无 token 的认证注册元数据；损坏显式失败，不借 Runtime DB 兜底。
    def _load_metadata(self) -> dict[str, Any]:
        if not self.metadata_path.exists():
            return {
                "version": 1,
                "host_id": None,
                "active_profile_id": None,
                "profiles": {},
                "login_epoch": "initial",
            }
        try:
            value = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ChatGPTOAuthError("ChatGPT OAuth metadata is unreadable.") from None
        if not isinstance(value, dict) or not isinstance(
            value.get("profiles", {}), dict
        ):
            raise ChatGPTOAuthError("ChatGPT OAuth metadata has an invalid shape.")
        value.setdefault("version", 1)
        value.setdefault("host_id", None)
        value.setdefault("active_profile_id", None)
        value.setdefault("profiles", {})
        value.setdefault("login_epoch", "initial")
        return value

    # 单文件原子发布非秘钥元数据，Unix 尽力收紧权限；不构成与系统凭据库的跨系统事务。
    def _save_metadata(self, value: dict[str, Any]) -> None:
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        # 明确字段白名单：即使调用方误带凭据，也不能落到明文元数据。
        value = {key: value.get(key) for key in (
            "version", "host_id", "active_profile_id", "profiles", "login_epoch"
        )}
        value["profiles"] = {
            pid: {key: raw.get(key) for key in ("client_id", "subject", "email", "name", "status", "login_revision")}
            for pid, raw in (value.get("profiles") or {}).items() if isinstance(raw, dict)
        }
        encoded = (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        atomic_write(self.metadata_path, encoded)
        if os.name != "nt":
            try:
                os.chmod(self.metadata_path, 0o600)
            except OSError:
                pass

    # 生成并保存本机 OAuth 注册主机身份；这是元数据身份，不是访问 token。
    @_serialized_auth
    def host_id(self) -> str:
        metadata = self._load_metadata()
        value = metadata.get("host_id")
        if isinstance(value, str) and value.startswith("urn:uuid:"):
            return value
        value = f"urn:uuid:{uuid.uuid4()}"
        metadata["host_id"] = value
        self._save_metadata(metadata)
        return value

    # 从颁发 client_id 摘要派生稳定本机 profile 身份；不是复用其他应用的客户端身份。
    @staticmethod
    def _profile_id(client_id: str) -> str:
        digest = hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:24]
        return f"chatgpt_{digest}"

    # 投影可公开账号元数据和活动选择；不返回 token、code 或 verifier。
    def profiles(self) -> list[dict[str, Any]]:
        metadata = self._load_metadata()
        active = metadata.get("active_profile_id")
        result = []
        for profile_id, raw in metadata["profiles"].items():
            if not isinstance(raw, dict):
                continue
            result.append(
                {
                    "profile_id": profile_id,
                    "email": raw.get("email"),
                    "name": raw.get("name"),
                    "status": raw.get("status", "registered"),
                    "active": profile_id == active,
                }
            )
        return sorted(
            result,
            key=lambda item: (
                not item["active"],
                item.get("email") or item["profile_id"],
            ),
        )

    # 验证已注册 profile 并返回非秘钥数据副本。
    def _profile(self, profile_id: str) -> dict[str, Any]:
        metadata = self._load_metadata()
        profile = metadata["profiles"].get(profile_id)
        if not isinstance(profile, dict):
            raise KeyError(profile_id)
        return dict(profile)

    # 显式切换本机活动账号并返回认证投影；不扩大原授予 scope。
    @_serialized_auth
    def select_profile(self, profile_id: str) -> ChatGPTAuthStatus:
        self._profile(profile_id)
        metadata = self._load_metadata()
        metadata["active_profile_id"] = profile_id
        self._save_metadata(metadata)
        return self.status(profile_id)

    # 读取明确选择的 profile；无选择返回空值，不猜测其他应用账号。
    def _active_profile_id(self) -> str | None:
        value = self._load_metadata().get("active_profile_id")
        return value if isinstance(value, str) and value else None

    # 校验 loopback callback 后生成限时 state/nonce/verifier，挑战只留内存；重授权绑定原客户端与账号。
    @_serialized_auth
    def begin_login(
        self, redirect_uri: str, *, profile_id: str | None = None
    ) -> dict[str, Any]:
        parsed = parse.urlparse(redirect_uri)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.path != "/auth/callback"
            or parsed.port is None
            or not 1 <= parsed.port <= 65535
            or parsed.query
        ):
            raise ValueError(
                "OAuth redirect_uri must be http://127.0.0.1:<port>/auth/callback"
            )
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError(
                "OAuth redirect_uri must not contain credentials or fragments"
            )

        metadata = self._load_metadata()
        requested_client_id = DYNAMIC_CLIENT_ID
        login_hint = None
        if profile_id:
            profile = self._profile(profile_id)
            requested_client_id = str(profile["client_id"])
            login_hint = profile.get("email")
            # 省略可选 id_token_hint：授权入口会进入 Web JSON/浏览器，不能携带 ID Token。

        state = self._new_secret()
        nonce = self._new_secret()
        verifier = self._new_secret(48)
        challenge = self._b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        attempt = PendingLogin(
            state=state,
            nonce=nonce,
            code_verifier=verifier,
            redirect_uri=redirect_uri,
            requested_client_id=requested_client_id,
            profile_id=profile_id,
            created_at=time.time(),
            login_epoch=metadata["login_epoch"],
            login_id=self._new_secret(16),
        )
        with self._pending_lock:
            now = time.time()
            self._pending = {
                key: value
                for key, value in self._pending.items()
                if now - value.created_at < LOGIN_TTL_SECONDS
            }
            if len(self._pending) >= 16:
                raise ChatGPTOAuthError("Too many pending ChatGPT sign-in attempts.")
            self._pending[state] = attempt

        params = {
            "response_type": "code",
            "client_id": requested_client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "resource": RESOURCE,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "ext_agent_host_id": self.host_id(),
        }
        if requested_client_id == DYNAMIC_CLIENT_ID:
            params["agent_name_hint"] = AGENT_NAME
        if login_hint:
            params["login_hint"] = str(login_hint)

        return {
            "auth_url": AUTHORIZATION_ENDPOINT + "?" + parse.urlencode(params),
            "expires_in": LOGIN_TTL_SECONDS,
            "return_to": redirect_uri,
            "login_id": attempt.login_id,
        }

    # 从回调参数取一个值供后续严格校验；不把解析结果写进日志。
    @staticmethod
    def _single(params: dict[str, Any], name: str) -> str | None:
        value = params.get(name)
        if isinstance(value, list):
            if len(value) != 1:
                raise ChatGPTOAuthError("OAuth callback contains ambiguous parameters.")
            value = value[0]
        if value in (None, ""):
            return None
        if not isinstance(value, str) or len(value) > 8192:
            raise ChatGPTOAuthError("OAuth callback contains invalid parameters.")
        return value

    # 保存服务新颁发的 client_id 元数据，固定 profile 关联；秘钥另存系统库。
    @_serialized_auth
    def _persist_registration(self, client_id: str) -> str:
        profile_id = self._profile_id(client_id)
        metadata = self._load_metadata()
        current = metadata["profiles"].get(profile_id)
        if not isinstance(current, dict):
            metadata["profiles"][profile_id] = {
                "client_id": client_id,
                "subject": None,
                "email": None,
                "name": None,
                "status": "registered",
            }
            self._save_metadata(metadata)
        elif current.get("client_id") != client_id:
            raise ChatGPTOAuthError(
                "Stored ChatGPT registration does not match the callback client."
            )
        return profile_id

    # 一次性消费有效 state，交换 code，校验 OIDC/nonce/账号，再保存系统凭据与非秘钥元数据；二者不宣称同事务。
    @_serialized_auth
    def complete_callback(self, params: dict[str, Any]) -> ChatGPTAuthStatus:
        # 所有安全字段先排除重复/超长/歧义；畸形请求不能消费有效挑战。
        for name in ("state", "code", "client_id", "error", "iss"):
            self._single(params, name)
        state = self._single(params, "state")
        if not state:
            raise ChatGPTOAuthError("OAuth callback is missing state.")
        with self._pending_lock:
            attempt = self._pending.pop(state, None)
        if attempt is None or time.time() - attempt.created_at >= LOGIN_TTL_SECONDS:
            raise ChatGPTOAuthError("OAuth callback state is unknown or expired.")
        if not secrets.compare_digest(state, attempt.state):
            raise ChatGPTOAuthError("OAuth callback state mismatch.")
        if attempt.login_epoch != self._load_metadata()["login_epoch"]:
            raise ChatGPTOAuthError("OAuth callback was cancelled by sign-out.")
        callback_issuer = self._single(params, "iss")
        if callback_issuer is not None and callback_issuer != ISSUER:
            raise ChatGPTOAuthError("OAuth callback issuer mismatch.")

        provider_error = self._single(params, "error")
        if provider_error:
            raise OAuthRejected(
                public_error_code(provider_error, "oauth_rejected"), "ChatGPT authorization was not completed."
            )

        code = self._single(params, "code")
        if not code:
            raise ChatGPTOAuthError("OAuth callback is missing the authorization code.")

        callback_client_id = self._single(params, "client_id")
        if attempt.requested_client_id == DYNAMIC_CLIENT_ID:
            if not callback_client_id or callback_client_id == DYNAMIC_CLIENT_ID:
                raise ChatGPTOAuthError(
                    "ChatGPT registration did not return an issued client ID."
                )
            client_id = callback_client_id
            profile_id = self._persist_registration(client_id)
        else:
            client_id = attempt.requested_client_id
            if callback_client_id and callback_client_id != client_id:
                raise ChatGPTOAuthError(
                    "OAuth callback returned a different client ID."
                )
            if not attempt.profile_id:
                raise ChatGPTOAuthError(
                    "Returning OAuth attempt lost its profile binding."
                )
            profile_id = attempt.profile_id

        token_response = self._token_request(
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": attempt.code_verifier,
                "redirect_uri": attempt.redirect_uri,
                "resource": RESOURCE,
            }
        )
        access_token = token_response.get("access_token")
        refresh_token = token_response.get("refresh_token")
        id_token = token_response.get("id_token")
        if not all(
            isinstance(value, str) and value
            for value in (access_token, refresh_token, id_token)
        ):
            raise ChatGPTOAuthError(
                "OAuth token response is missing renewable credentials."
            )

        claims = self._verify_id_token(
            id_token, client_id=client_id, nonce=attempt.nonce
        )
        subject = str(claims["sub"])
        old = self._profile(profile_id)
        if old.get("subject") and old["subject"] != subject:
            raise ChatGPTOAuthError("Reauthorization returned a different ChatGPT identity.")

        scopes = self._normalize_scopes(token_response.get("scope"))
        expires_at = self._expires_at(token_response)
        secret_record = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "id_token": id_token,
            "expires_at": expires_at,
            "scope": " ".join(scopes),
            "subject": subject,
            "client_id": client_id,
        }
        self.credentials.save(profile_id, secret_record)

        metadata = self._load_metadata()
        metadata["profiles"][profile_id] = {
            "client_id": client_id,
            "subject": subject,
            "email": claims.get("email"),
            "name": claims.get("name"),
            "status": "connected",
            "login_revision": attempt.login_id,
        }
        metadata["active_profile_id"] = profile_id
        self._save_metadata(metadata)
        return self.status(profile_id)

    # 规范化授予 scope 为排序去重元组；需求 scope 不等于已经获得授权。
    @staticmethod
    def _normalize_scopes(value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            values = value.split()
        elif isinstance(value, list):
            values = [str(item) for item in value]
        else:
            values = []
        return tuple(sorted({item for item in values if item}))

    # 使用服务颁发的真实寿命，不把短寿命 token 延长为六十秒；缺项/非法值拒绝使用。
    @staticmethod
    def _expires_at(value: dict[str, Any]) -> int:
        seconds = value.get("expires_in")
        if type(seconds) is not int or not 0 < seconds <= 604800:
            raise ChatGPTOAuthError("OAuth token response has an invalid lifetime.")
        return int(time.time()) + seconds

    # 用 JWKS 校验签名、issuer/audience/expiry/sub 及 nonce；校验错误脱敏，不能信任未验证 claims。
    def _verify_id_token(
        self, token: str, *, client_id: str, nonce: str | None
    ) -> dict[str, Any]:
        try:
            # OIDC compact JWT 仅接受规范的未填充 Base64URL；旧库的宽松解码不能扩大合同。
            if not isinstance(token, str) or len(token) > 32768 or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
                raise ValueError("invalid compact JWT")
            for segment in token.split("."):
                raw = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
                if base64.urlsafe_b64encode(raw).decode().rstrip("=") != segment:
                    raise ValueError("non-canonical compact JWT")
            key = self._jwks.get_signing_key_from_jwt(token).key
            if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
                raise ValueError("OIDC requires an RSA public key of at least 2048 bits")
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=client_id,
                issuer=ISSUER,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except Exception as exc:
            raise ChatGPTOAuthError(
                "ChatGPT identity token verification failed."
            ) from None
        if nonce is not None and claims.get("nonce") != nonce:
            raise ChatGPTOAuthError("ChatGPT identity token nonce mismatch.")
        audiences = claims.get("aud")
        if (claims.get("azp") is not None and claims["azp"] != client_id) or (
            isinstance(audiences, list) and len(audiences) > 1 and claims.get("azp") != client_id
        ):
            raise ChatGPTOAuthError("ChatGPT identity token authorized party mismatch.")
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise ChatGPTOAuthError("ChatGPT identity token subject is invalid.")
        return claims

    # 向固定 token endpoint 提交 OAuth 表单；code/verifier/token 不进入 Runtime 对象。
    def _token_request(self, parameters: dict[str, str]) -> dict[str, Any]:
        return self._form_request(TOKEN_ENDPOINT, parameters)

    # 在认证边界发 HTTP 表单并分类脱敏拒绝；网络失败不凭重试猜测已轮转 token 的状态。
    def _form_request(self, url: str, parameters: dict[str, str]) -> dict[str, Any]:
        # 认证参数只进入固定端点的禁止重定向传输；远端错误码经白名单投影后才公开。
        body = parse.urlencode(parameters).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "accept": "application/json",
                "user-agent": f"myth-runtime/{__version__}",
            },
        )
        try:
            with open_credential_request(req, timeout=self.timeout) as response:
                raw = read_bounded(response)
        except error.HTTPError as exc:
            with exc:
                raw = read_bounded(exc)
            code = "oauth_rejected"
            try:
                payload = json.loads(raw.decode("utf-8"))
                if isinstance(payload, dict) and isinstance(payload.get("error"), str):
                    code = public_error_code(payload["error"], code)
            except Exception:
                pass
            raise OAuthRejected(
                code,
                f"OAuth endpoint rejected the request ({exc.code}, {code}).",
                status=exc.code,
            ) from None
        except error.URLError as exc:
            raise ChatGPTOAuthError("OAuth endpoint could not be reached.") from None
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ChatGPTOAuthError("OAuth endpoint returned invalid JSON.") from None
        if not isinstance(value, dict):
            raise ChatGPTOAuthError("OAuth endpoint returned an invalid response.")
        return value

    # 返回账号/授予 scope/到期信息投影；不刷新 token 或公开秘钥，ready 只表示计划权限已授予。
    @_serialized_auth
    def status(self, profile_id: str | None = None) -> ChatGPTAuthStatus:
        # 先检查公开账号状态，再读取安全库；状态查询不触发刷新或其他远端调用。
        profile_id = profile_id or self._active_profile_id()
        if not profile_id:
            return ChatGPTAuthStatus(
                False, False, False, None, None, None, None, (), "not_signed_in"
            )
        try:
            profile = self._profile(profile_id)
        except KeyError:
            return ChatGPTAuthStatus(
                False, False, False, None, None, None, None, (), "profile_missing"
            )
        if profile.get("status") in {"signed_out", "reauth_required", "refresh_pending"}:
            return ChatGPTAuthStatus(False, False, False, profile_id,
                profile.get("email"), profile.get("name"), None, (),
                "reauth_required" if profile.get("status") != "signed_out" else "signed_out")
        try:
            stored = self.credentials.load(profile_id)
        except CredentialStoreUnavailable as exc:
            return ChatGPTAuthStatus(
                False,
                False,
                False,
                profile_id,
                profile.get("email"),
                profile.get("name"),
                None,
                (),
                str(exc),
            )
        if not stored:
            return ChatGPTAuthStatus(
                False,
                False,
                False,
                profile_id,
                profile.get("email"),
                profile.get("name"),
                None,
                (),
                profile.get("status") or "signed_out",
            )
        scopes = self._normalize_scopes(stored.get("scope"))
        sharing = "chatgpt.tokens.use.direct" in scopes and "resource.invoke" in scopes
        expires_at = int(stored.get("expires_at") or 0) or None
        return ChatGPTAuthStatus(
            connected=True,
            sharing=sharing,
            ready=sharing,
            profile_id=profile_id,
            email=profile.get("email"),
            name=profile.get("name"),
            expires_at=expires_at,
            scopes=scopes,
            reason=None if sharing else "chatgpt_plan_usage_not_granted",
            login_revision=profile.get("login_revision"),
        )

    # 删除失效系统秘钥并标记需要用户重新登录；不复用已失效 refresh token。
    def _mark_reauth_required(self, profile_id: str) -> None:
        self.credentials.delete(profile_id)
        metadata = self._load_metadata()
        profile = metadata["profiles"].get(profile_id)
        if isinstance(profile, dict):
            profile["status"] = "reauth_required"
            self._save_metadata(metadata)

    # 检查明确账号和已授予 scope，到期前刷新后仅交给传输供应函数；不得记录返回秘钥。
    @_serialized_auth
    def access_token(self, profile_id: str | None = None) -> str:
        profile_id = profile_id or self._active_profile_id()
        if not profile_id:
            raise ChatGPTOAuthError("No ChatGPT account is selected.")
        if self._profile(profile_id).get("status") in {"signed_out", "reauth_required", "refresh_pending"}:
            raise ChatGPTOAuthError("The selected ChatGPT account requires sign-in.")
        stored = self.credentials.load(profile_id)
        if not stored:
            raise ChatGPTOAuthError("The selected ChatGPT account is signed out.")
        scopes = self._normalize_scopes(stored.get("scope"))
        if "chatgpt.tokens.use.direct" not in scopes or "resource.invoke" not in scopes:
            raise ChatGPTOAuthError("ChatGPT plan usage permission is not enabled.")
        if (
            int(stored.get("expires_at") or 0)
            <= int(time.time()) + REFRESH_SKEW_SECONDS
        ):
            stored = self._refresh(profile_id)
        # 轮转可能缩减 scope；必须按新颁发的凭据复核权限。
        scopes = self._normalize_scopes(stored.get("scope"))
        if not {"chatgpt.tokens.use.direct", "resource.invoke"}.issubset(scopes):
            raise ChatGPTOAuthError("ChatGPT plan usage permission is not enabled.")
        token = stored.get("access_token")
        if not isinstance(token, str) or not token:
            raise ChatGPTOAuthError("Stored ChatGPT access token is unavailable.")
        return token

    # 跨线程和进程串行刷新并重新读秘钥；明确失效要求重授权，保存轮转凭据后返回；与元数据不构成跨系统事务。
    @_serialized_auth
    def _refresh(self, profile_id: str) -> dict[str, Any]:
        # 已持有认证聚合锁；保持与登录/退出同一串行顺序。
        if self._profile(profile_id).get("status") in {"signed_out", "reauth_required", "refresh_pending"}:
            raise ChatGPTOAuthError("The selected ChatGPT account requires sign-in.")
        stored = self.credentials.load(profile_id)
        if not stored:
            raise ChatGPTOAuthError("The selected ChatGPT account is signed out.")
        if (
            int(stored.get("expires_at") or 0)
            > int(time.time()) + REFRESH_SKEW_SECONDS
        ):
            return stored
        refresh_token = stored.get("refresh_token")
        client_id = stored.get("client_id")
        if (
            not isinstance(refresh_token, str)
            or not refresh_token
            or not isinstance(client_id, str)
            or not client_id
        ):
            self._mark_reauth_required(profile_id)
            raise ChatGPTOAuthError(
                "ChatGPT credentials cannot be refreshed; sign in again."
            )
        # 派发轮转前持久记录未结算状态；中途进程退出后，另一个进程不能再用旧 refresh token。
        metadata = self._load_metadata()
        metadata["profiles"][profile_id]["status"] = "refresh_pending"
        self._save_metadata(metadata)
        try:
            value = self._token_request(
                {
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": refresh_token,
                    "resource": RESOURCE,
                }
            )
        except OAuthRejected as exc:
            if exc.code in _TERMINAL_REFRESH_ERRORS:
                self._mark_reauth_required(profile_id)
            elif exc.status is not None and 400 <= exc.status < 500:
                metadata = self._load_metadata()
                metadata["profiles"][profile_id]["status"] = "connected"
                self._save_metadata(metadata)
            raise
        except (ChatGPTOAuthError, OSError, RuntimeError):
            # 轮转结果不明时不能重复提交旧 refresh token；关闭本地认证并要求重新登录。
            self._mark_reauth_required(profile_id)
            raise ChatGPTOAuthError("ChatGPT refresh could not be confirmed; sign in again.") from None

        new_access = value.get("access_token")
        if not isinstance(new_access, str) or not new_access:
            self._mark_reauth_required(profile_id)
            raise ChatGPTOAuthError(
                "Refresh response did not contain an access token."
            )
        new_refresh = value.get("refresh_token")
        if not isinstance(new_refresh, str) or not new_refresh:
            new_refresh = refresh_token
        new_id_token = value.get("id_token")
        if isinstance(new_id_token, str) and new_id_token:
            try:
                claims = self._verify_id_token(new_id_token, client_id=client_id, nonce=None)
            except ChatGPTOAuthError:
                self._mark_reauth_required(profile_id)
                raise
            if str(claims.get("sub")) != str(stored.get("subject")):
                self._mark_reauth_required(profile_id)
                raise ChatGPTOAuthError(
                    "Refreshed ChatGPT identity does not match the selected account."
                )
        else:
            new_id_token = stored.get("id_token")

        scopes = self._normalize_scopes(value["scope"] if "scope" in value else stored.get("scope"))
        updated = {
            **stored,
            "access_token": new_access,
            "refresh_token": new_refresh,
            "id_token": new_id_token,
            "expires_at": self._expires_at(value),
            "scope": " ".join(scopes),
        }
        try:
            self.credentials.save(profile_id, updated)
        except CredentialStoreUnavailable:
            # 远端已轮转但本机未保存：元数据先阻止旧凭据再次被使用。
            metadata = self._load_metadata()
            metadata["profiles"][profile_id]["status"] = "reauth_required"
            self._save_metadata(metadata)
            raise
        # 系统库先保存新轮转值，元数据才回到 connected；两个系统之间的崩溃窗口保守要求重授权。
        metadata = self._load_metadata()
        metadata["profiles"][profile_id]["status"] = "connected"
        self._save_metadata(metadata)
        return updated

    # 用有效短期 token 读取计划模型目录并返回可公开字段；模型列表不等于成功推理。
    @_serialized_auth
    def list_models(self, profile_id: str | None = None, *, force: bool = False) -> list[dict[str, str]]:
        profile_id = profile_id or self._active_profile_id()
        # 即使命中目录，也先读取系统凭据并复核有效性/权限；缓存不授予调用权。
        token = self.access_token(profile_id)
        metadata = self._load_metadata()
        profile = self._profile(profile_id)
        key = (str(self.root), profile_id, metadata["login_epoch"], profile.get("login_revision"))
        now = time.monotonic()
        with _MODEL_CATALOG_LOCK:
            cached = _MODEL_CATALOG_CACHE.get(key)
        if not force and cached and now - cached[0] < 30:
            return [dict(item) for item in cached[1]]
        result = self._fetch_models(token)
        with _MODEL_CATALOG_LOCK:
            if len(_MODEL_CATALOG_CACHE) >= 16:
                _MODEL_CATALOG_CACHE.clear()
            _MODEL_CATALOG_CACHE[key] = (time.monotonic(), tuple(dict(item) for item in result))
        return result

    # 使用一次有效凭据读取目录；只留公开字段，HTTP 重定向不携带 token 继续执行。
    def _fetch_models(self, token: str) -> list[dict[str, str]]:
        # 先有界读取固定目录，再筛选公开身份；供应商回显 token 的模型标识必须拒绝。
        req = request.Request(
            f"{RESOURCE}/models",
            headers={
                "authorization": f"Bearer {token}",
                "accept": "application/json",
                "user-agent": f"myth-runtime/{__version__}",
            },
        )
        try:
            with open_credential_request(req, timeout=self.timeout) as response:
                raw = read_bounded(response)
        except error.HTTPError as exc:
            exc.close()
            raise ChatGPTOAuthError(
                f"ChatGPT model catalog request failed ({exc.code})."
            ) from None
        except error.URLError as exc:
            raise ChatGPTOAuthError(
                "ChatGPT model catalog could not be reached."
            ) from None
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ChatGPTOAuthError(
                "ChatGPT model catalog returned invalid JSON."
            ) from None
        rows = value.get("models") if isinstance(value, dict) else None
        if not isinstance(rows, list) and isinstance(value, dict):
            rows = value.get("data")
        if not isinstance(rows, list):
            raise ChatGPTOAuthError("ChatGPT model catalog has an invalid shape.")
        result = []
        if len(rows) > 1000:
            raise ChatGPTOAuthError("ChatGPT model catalog exceeds the model limit.")
        for item in rows:
            if not isinstance(item, dict):
                continue
            if item.get("visibility") not in {None, "list"}:
                continue
            slug = item.get("slug") or item.get("id")
            if not isinstance(slug, str) or not slug or len(slug) > 200 or token in slug:
                continue
            display = item.get("display_name") or slug
            result.append({"slug": slug, "display_name": redact_response(str(display)[:300], token)})
        return result

    # 尝试固定端点远端撤销；错误作为退出结果保留，不宣称不可用网络下已远端撤销。
    def _revoke_refresh_token(self, refresh_token: str, client_id: str) -> None:
        body = parse.urlencode(
            {
                "token": refresh_token,
                "token_type_hint": "refresh_token",
                "client_id": client_id,
            }
        ).encode("utf-8")
        req = request.Request(
            REVOCATION_ENDPOINT,
            data=body,
            method="POST",
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "user-agent": f"myth-runtime/{__version__}",
            },
        )
        try:
            with open_credential_request(req, timeout=self.timeout) as response:
                read_bounded(response)
        except error.HTTPError as exc:
            exc.close()
            raise ChatGPTOAuthError(
                f"Remote ChatGPT session revocation failed ({exc.code})."
            ) from None
        except error.URLError as exc:
            raise ChatGPTOAuthError(
                "Remote ChatGPT session revocation could not be confirmed."
            ) from None

    # 先关闭本机使用权，再尝试远端撤销并清理系统凭据；保留撤销是否成功的事实。
    @_serialized_auth
    def logout(self, profile_id: str | None = None) -> dict[str, Any]:
        # 退出先持久取消旧挑战，包含其他管理器的待完成登录，不能在退出后重新写回凭据。
        metadata = self._load_metadata()
        profile_id = profile_id or metadata.get("active_profile_id")
        metadata["login_epoch"] = self._new_secret()
        profile = metadata["profiles"].get(profile_id)
        if isinstance(profile, dict):
            # 先关闭本机使用权，远端撤销/系统库删除期间崩溃也不能继续认证。
            profile["status"] = "signed_out"
        if metadata.get("active_profile_id") == profile_id:
            metadata["active_profile_id"] = None
        self._save_metadata(metadata)
        with self._pending_lock:
            self._pending.clear()
        if not profile_id:
            return {"signed_out": True, "remote_revoked": True}
        stored = self.credentials.load(profile_id)
        remote_revoked = True
        if stored:
            refresh_token = stored.get("refresh_token")
            client_id = stored.get("client_id")
            if (
                isinstance(refresh_token, str)
                and refresh_token
                and isinstance(client_id, str)
                and client_id
            ):
                try:
                    self._revoke_refresh_token(refresh_token, client_id)
                except ChatGPTOAuthError:
                    remote_revoked = False
        # 未完成分块也可能留下系统库记录，load=None 时仍要执行清理。
        self.credentials.delete(profile_id)

        metadata = self._load_metadata()
        profile = metadata["profiles"].get(profile_id)
        if isinstance(profile, dict):
            profile["status"] = "signed_out"
        if metadata.get("active_profile_id") == profile_id:
            metadata["active_profile_id"] = None
        self._save_metadata(metadata)
        return {
            "signed_out": True,
            "remote_revoked": remote_revoked,
            "profile_id": profile_id,
        }


def run_loopback_login(
    manager: ChatGPTAuthManager,
    *,
    profile_id: str | None = None,
    open_browser: bool = True,
    timeout: float = 300.0,
) -> ChatGPTAuthStatus:
    """开临时 loopback 回调服务并等待有限时间；关闭服务时挑战结束，不能把 code 写到通用 HTTP 日志。"""

    result: dict[str, Any] = {}
    done = threading.Event()

    # 固定 loopback 路由的 HTTP 入站适配器；只解析有界参数/返回投影，业务状态仍归仓储与用例。
    class Handler(BaseHTTPRequestHandler):
        # 回调只需一条短请求；半开请求不能无限占用临时监听线程。
        def setup(self):
            super().setup()
            self.connection.settimeout(15.0)

        # 禁用回调请求日志，避免 code/state 经 URL 泄露。
        def log_message(self, *_args) -> None:
            return

        # 仅处理固定 callback，交认证管理器完成挑战，返回脱敏结果。
        def do_GET(self) -> None:
            parsed = parse.urlparse(self.path)
            if parsed.path != "/auth/callback":
                self.send_response(404)
                self.end_headers()
                return
            try:
                params = parse.parse_qs(parsed.query, keep_blank_values=True, max_num_fields=20)
                incoming = manager._single(params, "state")
                if (self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}"
                        or not incoming or not secrets.compare_digest(incoming, expected_state)):
                    raise ChatGPTOAuthError("Unrelated OAuth callback.")
            except (ValueError, ChatGPTOAuthError):
                # 未持有本次 state 的请求不能结束 CLI 登录等待，也不能消耗挑战。
                self.send_response(400)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                return
            try:
                status = manager.complete_callback(params)
                result["status"] = status
                body = b"Myth is connected to ChatGPT. You can close this window."
                self.send_response(200)
            except Exception as exc:
                result["error"] = exc
                body = b"Myth could not complete ChatGPT sign-in. Return to the terminal for details."
                self.send_response(400)
            self.send_header("content-type", "text/plain; charset=utf-8")
            self.send_header("cache-control", "no-store")
            self.send_header("referrer-policy", "no-referrer")
            self.send_header("x-content-type-options", "nosniff")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            done.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 0.5
    redirect_uri = f"http://127.0.0.1:{server.server_port}/auth/callback"
    attempt = manager.begin_login(redirect_uri, profile_id=profile_id)
    expected_state = parse.parse_qs(parse.urlparse(attempt["auth_url"]).query)["state"][0]
    if open_browser:
        webbrowser.open(attempt["auth_url"])
    deadline = time.monotonic() + timeout
    try:
        while not done.is_set() and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
        with manager._pending_lock:
            manager._pending.pop(expected_state, None)
    if not done.is_set():
        raise ChatGPTOAuthError("ChatGPT sign-in timed out.")
    if "error" in result:
        raise result["error"]
    return result["status"]
