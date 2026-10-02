"""Myth-owned Sign in with ChatGPT OAuth for open-source local clients.

Security boundaries:
- authorization code + PKCE S256 + fresh state + OIDC nonce;
- loopback-only callbacks;
- ID-token signature/issuer/audience/expiry/nonce validation;
- credentials live in the OS credential store, never Runtime SQLite/events/objects;
- metadata files contain no access/refresh/ID tokens;
- refreshes are serialized across threads/processes;
- logout attempts remote refresh-token revocation, then clears local credentials.

The flow follows OpenAI's public OSS Sign in with ChatGPT contract.  Myth does
not read another application's auth files and does not reuse another
application's OAuth client identity.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
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
from keyring.errors import PasswordDeleteError

from ..artifacts import atomic_write


ISSUER = "https://auth.openai.com"
AUTHORIZATION_ENDPOINT = f"{ISSUER}/api/accounts/authorize"
TOKEN_ENDPOINT = f"{ISSUER}/api/accounts/oauth/token"
REVOCATION_ENDPOINT = f"{ISSUER}/api/accounts/oauth/revoke"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
RESOURCE = "https://api.openai.com/v1"
DYNAMIC_CLIENT_ID = "dynamic_agent_client"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
AGENT_NAME = "Myth"
KEYRING_SERVICE = "Myth ChatGPT OAuth"
REFRESH_SKEW_SECONDS = 300
LOGIN_TTL_SECONDS = 600

_TERMINAL_REFRESH_ERRORS = {
    "invalid_grant",
    "invalid_refresh_token",
    "token_expired",
    "refresh_token_expired",
    "refresh_token_invalidated",
    "refresh_token_reused",
}


class ChatGPTOAuthError(RuntimeError):
    """OAuth failure whose message never contains codes, verifiers or tokens."""


class OAuthRejected(ChatGPTOAuthError):
    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class CredentialStoreUnavailable(ChatGPTOAuthError):
    pass


class CredentialStore(Protocol):
    def load(self, profile_id: str) -> dict[str, Any] | None: ...
    def save(self, profile_id: str, value: dict[str, Any]) -> None: ...
    def delete(self, profile_id: str) -> None: ...


class KeyringCredentialStore:
    """Fail-closed OS credential storage.

    No plaintext-file fallback is provided.  If the host has no usable
    credential backend, OAuth login is unavailable until one is configured.
    """

    def __init__(self, service: str = KEYRING_SERVICE) -> None:
        self.service = service

    @staticmethod
    def _backend():
        backend = keyring.get_keyring()
        identity = f"{type(backend).__module__}.{type(backend).__name__}".lower()
        priority = getattr(backend, "priority", 0)
        try:
            numeric_priority = float(priority)
        except (TypeError, ValueError):
            numeric_priority = 0.0
        if (
            numeric_priority <= 0
            or "fail" in identity
            or "plaintext" in identity
            or "null" in identity
        ):
            raise CredentialStoreUnavailable(
                "No secure OS credential store is available. "
                "Configure Windows Credential Manager, macOS Keychain, or a secure Secret Service backend."
            )
        return backend

    def load(self, profile_id: str) -> dict[str, Any] | None:
        raw = self._backend().get_password(self.service, profile_id)
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CredentialStoreUnavailable("Stored ChatGPT credentials are unreadable.") from exc
        if not isinstance(value, dict):
            raise CredentialStoreUnavailable("Stored ChatGPT credentials have an invalid shape.")
        return value

    def save(self, profile_id: str, value: dict[str, Any]) -> None:
        self._backend().set_password(
            self.service,
            profile_id,
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        )

    def delete(self, profile_id: str) -> None:
        try:
            self._backend().delete_password(self.service, profile_id)
        except PasswordDeleteError:
            pass


@dataclass(frozen=True)
class PendingLogin:
    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str
    requested_client_id: str
    profile_id: str | None
    created_at: float


@dataclass(frozen=True)
class ChatGPTAuthStatus:
    connected: bool
    sharing: bool
    ready: bool
    profile_id: str | None
    email: str | None
    name: str | None
    expires_at: int | None
    scopes: tuple[str, ...]
    reason: str | None = None

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
        }


class _CrossProcessLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(self.path, "a+b")
        self.file.seek(0, os.SEEK_END)
        if self.file.tell() == 0:
            self.file.write(b"\0")
            self.file.flush()
        self.file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *_):
        if self.file is None:
            return
        try:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close()
            self.file = None


class ChatGPTAuthManager:
    def __init__(
        self,
        root: str | Path,
        *,
        credential_store: CredentialStore | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.root = Path(root).resolve()
        self.auth_dir = self.root / ".runtime" / "oauth"
        self.metadata_path = self.auth_dir / "chatgpt.json"
        self.timeout = timeout
        self.credentials = credential_store or KeyringCredentialStore()
        self._pending: dict[str, PendingLogin] = {}
        self._pending_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._jwks = jwt.PyJWKClient(JWKS_URL)
        self.auth_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @staticmethod
    def _new_secret(nbytes: int = 32) -> str:
        return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b"=").decode("ascii")

    def _load_metadata(self) -> dict[str, Any]:
        if not self.metadata_path.exists():
            return {"version": 1, "host_id": None, "active_profile_id": None, "profiles": {}}
        try:
            value = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ChatGPTOAuthError("ChatGPT OAuth metadata is unreadable.") from exc
        if not isinstance(value, dict) or not isinstance(value.get("profiles", {}), dict):
            raise ChatGPTOAuthError("ChatGPT OAuth metadata has an invalid shape.")
        value.setdefault("version", 1)
        value.setdefault("host_id", None)
        value.setdefault("active_profile_id", None)
        value.setdefault("profiles", {})
        return value

    def _save_metadata(self, value: dict[str, Any]) -> None:
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        atomic_write(self.metadata_path, encoded)
        if os.name != "nt":
            try:
                os.chmod(self.metadata_path, 0o600)
            except OSError:
                pass

    def host_id(self) -> str:
        metadata = self._load_metadata()
        value = metadata.get("host_id")
        if isinstance(value, str) and value.startswith("urn:uuid:"):
            return value
        value = f"urn:uuid:{uuid.uuid4()}"
        metadata["host_id"] = value
        self._save_metadata(metadata)
        return value

    @staticmethod
    def _profile_id(client_id: str) -> str:
        digest = hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:24]
        return f"chatgpt_{digest}"

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
        return sorted(result, key=lambda item: (not item["active"], item.get("email") or item["profile_id"]))

    def _profile(self, profile_id: str) -> dict[str, Any]:
        metadata = self._load_metadata()
        profile = metadata["profiles"].get(profile_id)
        if not isinstance(profile, dict):
            raise KeyError(profile_id)
        return dict(profile)

    def select_profile(self, profile_id: str) -> ChatGPTAuthStatus:
        self._profile(profile_id)
        metadata = self._load_metadata()
        metadata["active_profile_id"] = profile_id
        self._save_metadata(metadata)
        return self.status(profile_id)

    def _active_profile_id(self) -> str | None:
        value = self._load_metadata().get("active_profile_id")
        return value if isinstance(value, str) and value else None

    def begin_login(self, redirect_uri: str, *, profile_id: str | None = None) -> dict[str, Any]:
        parsed = parse.urlparse(redirect_uri)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path != "/auth/callback":
            raise ValueError("OAuth redirect_uri must be http://127.0.0.1:<port>/auth/callback")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("OAuth redirect_uri must not contain credentials or fragments")

        metadata = self._load_metadata()
        requested_client_id = DYNAMIC_CLIENT_ID
        id_token_hint = None
        login_hint = None
        if profile_id:
            profile = self._profile(profile_id)
            requested_client_id = str(profile["client_id"])
            login_hint = profile.get("email")
            stored = self.credentials.load(profile_id)
            if stored and isinstance(stored.get("id_token"), str):
                id_token_hint = stored["id_token"]

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
        )
        with self._pending_lock:
            now = time.time()
            self._pending = {
                key: value
                for key, value in self._pending.items()
                if now - value.created_at < LOGIN_TTL_SECONDS
            }
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
            "agent_name_hint": AGENT_NAME,
        }
        if id_token_hint:
            params["id_token_hint"] = id_token_hint
        if login_hint:
            params["login_hint"] = str(login_hint)

        return {
            "auth_url": AUTHORIZATION_ENDPOINT + "?" + parse.urlencode(params),
            "expires_in": LOGIN_TTL_SECONDS,
            "return_to": redirect_uri,
        }

    @staticmethod
    def _single(params: dict[str, Any], name: str) -> str | None:
        value = params.get(name)
        if isinstance(value, list):
            value = value[0] if value else None
        return str(value) if value not in (None, "") else None

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
            raise ChatGPTOAuthError("Stored ChatGPT registration does not match the callback client.")
        return profile_id

    def complete_callback(self, params: dict[str, Any]) -> ChatGPTAuthStatus:
        state = self._single(params, "state")
        if not state:
            raise ChatGPTOAuthError("OAuth callback is missing state.")
        with self._pending_lock:
            attempt = self._pending.pop(state, None)
        if attempt is None or time.time() - attempt.created_at >= LOGIN_TTL_SECONDS:
            raise ChatGPTOAuthError("OAuth callback state is unknown or expired.")
        if not secrets.compare_digest(state, attempt.state):
            raise ChatGPTOAuthError("OAuth callback state mismatch.")

        provider_error = self._single(params, "error")
        if provider_error:
            raise OAuthRejected(provider_error, "ChatGPT authorization was not completed.")

        code = self._single(params, "code")
        if not code:
            raise ChatGPTOAuthError("OAuth callback is missing the authorization code.")

        callback_client_id = self._single(params, "client_id")
        if attempt.requested_client_id == DYNAMIC_CLIENT_ID:
            if not callback_client_id or callback_client_id == DYNAMIC_CLIENT_ID:
                raise ChatGPTOAuthError("ChatGPT registration did not return an issued client ID.")
            client_id = callback_client_id
            profile_id = self._persist_registration(client_id)
        else:
            client_id = attempt.requested_client_id
            if callback_client_id and callback_client_id != client_id:
                raise ChatGPTOAuthError("OAuth callback returned a different client ID.")
            if not attempt.profile_id:
                raise ChatGPTOAuthError("Returning OAuth attempt lost its profile binding.")
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
        if not all(isinstance(value, str) and value for value in (access_token, refresh_token, id_token)):
            raise ChatGPTOAuthError("OAuth token response is missing renewable credentials.")

        claims = self._verify_id_token(id_token, client_id=client_id, nonce=attempt.nonce)
        subject = str(claims["sub"])
        if attempt.profile_id:
            old = self._profile(profile_id)
            if old.get("subject") and old["subject"] != subject:
                raise ChatGPTOAuthError("Reauthorization returned a different ChatGPT identity.")

        scopes = self._normalize_scopes(token_response.get("scope"))
        expires_in = int(token_response.get("expires_in") or 3600)
        expires_at = int(time.time()) + max(60, expires_in)
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
        }
        metadata["active_profile_id"] = profile_id
        self._save_metadata(metadata)
        return self.status(profile_id)

    @staticmethod
    def _normalize_scopes(value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            values = value.split()
        elif isinstance(value, list):
            values = [str(item) for item in value]
        else:
            values = []
        return tuple(sorted({item for item in values if item}))

    def _verify_id_token(self, token: str, *, client_id: str, nonce: str | None) -> dict[str, Any]:
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=client_id,
                issuer=ISSUER,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except Exception as exc:
            raise ChatGPTOAuthError("ChatGPT identity token verification failed.") from exc
        if nonce is not None and claims.get("nonce") != nonce:
            raise ChatGPTOAuthError("ChatGPT identity token nonce mismatch.")
        return claims

    def _token_request(self, parameters: dict[str, str]) -> dict[str, Any]:
        return self._form_request(TOKEN_ENDPOINT, parameters)

    def _form_request(self, url: str, parameters: dict[str, str]) -> dict[str, Any]:
        body = parse.urlencode(parameters).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "accept": "application/json",
                "user-agent": "myth-runtime/0.19",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read()
        except error.HTTPError as exc:
            raw = exc.read()
            code = "oauth_rejected"
            description = "OAuth endpoint rejected the request."
            try:
                payload = json.loads(raw.decode("utf-8"))
                if isinstance(payload, dict):
                    code = str(payload.get("error") or code)
                    description = str(payload.get("error_description") or payload.get("message") or description)
            except Exception:
                pass
            raise OAuthRejected(code, description[:300], status=exc.code) from exc
        except error.URLError as exc:
            raise ChatGPTOAuthError("OAuth endpoint could not be reached.") from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ChatGPTOAuthError("OAuth endpoint returned invalid JSON.") from exc
        if not isinstance(value, dict):
            raise ChatGPTOAuthError("OAuth endpoint returned an invalid response.")
        return value

    def status(self, profile_id: str | None = None) -> ChatGPTAuthStatus:
        profile_id = profile_id or self._active_profile_id()
        if not profile_id:
            return ChatGPTAuthStatus(False, False, False, None, None, None, None, (), "not_signed_in")
        try:
            profile = self._profile(profile_id)
        except KeyError:
            return ChatGPTAuthStatus(False, False, False, None, None, None, None, (), "profile_missing")
        try:
            stored = self.credentials.load(profile_id)
        except CredentialStoreUnavailable as exc:
            return ChatGPTAuthStatus(False, False, False, profile_id, profile.get("email"), profile.get("name"), None, (), str(exc))
        if not stored:
            return ChatGPTAuthStatus(False, False, False, profile_id, profile.get("email"), profile.get("name"), None, (), profile.get("status") or "signed_out")
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
        )

    def _mark_reauth_required(self, profile_id: str) -> None:
        self.credentials.delete(profile_id)
        metadata = self._load_metadata()
        profile = metadata["profiles"].get(profile_id)
        if isinstance(profile, dict):
            profile["status"] = "reauth_required"
            self._save_metadata(metadata)

    def access_token(self, profile_id: str | None = None) -> str:
        profile_id = profile_id or self._active_profile_id()
        if not profile_id:
            raise ChatGPTOAuthError("No ChatGPT account is selected.")
        stored = self.credentials.load(profile_id)
        if not stored:
            raise ChatGPTOAuthError("The selected ChatGPT account is signed out.")
        scopes = self._normalize_scopes(stored.get("scope"))
        if "chatgpt.tokens.use.direct" not in scopes or "resource.invoke" not in scopes:
            raise ChatGPTOAuthError("ChatGPT plan usage permission is not enabled.")
        if int(stored.get("expires_at") or 0) <= int(time.time()) + REFRESH_SKEW_SECONDS:
            stored = self._refresh(profile_id)
        token = stored.get("access_token")
        if not isinstance(token, str) or not token:
            raise ChatGPTOAuthError("Stored ChatGPT access token is unavailable.")
        return token

    def _refresh(self, profile_id: str) -> dict[str, Any]:
        with self._refresh_lock, _CrossProcessLock(self.auth_dir / f"refresh-{profile_id}.lock"):
            stored = self.credentials.load(profile_id)
            if not stored:
                raise ChatGPTOAuthError("The selected ChatGPT account is signed out.")
            if int(stored.get("expires_at") or 0) > int(time.time()) + REFRESH_SKEW_SECONDS:
                return stored
            refresh_token = stored.get("refresh_token")
            client_id = stored.get("client_id")
            if not isinstance(refresh_token, str) or not refresh_token or not isinstance(client_id, str) or not client_id:
                self._mark_reauth_required(profile_id)
                raise ChatGPTOAuthError("ChatGPT credentials cannot be refreshed; sign in again.")
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
                raise

            new_access = value.get("access_token")
            if not isinstance(new_access, str) or not new_access:
                raise ChatGPTOAuthError("Refresh response did not contain an access token.")
            new_refresh = value.get("refresh_token")
            if not isinstance(new_refresh, str) or not new_refresh:
                new_refresh = refresh_token
            new_id_token = value.get("id_token")
            if isinstance(new_id_token, str) and new_id_token:
                claims = self._verify_id_token(new_id_token, client_id=client_id, nonce=None)
                if str(claims.get("sub")) != str(stored.get("subject")):
                    self._mark_reauth_required(profile_id)
                    raise ChatGPTOAuthError("Refreshed ChatGPT identity does not match the selected account.")
            else:
                new_id_token = stored.get("id_token")

            scopes = self._normalize_scopes(value.get("scope")) or self._normalize_scopes(stored.get("scope"))
            updated = {
                **stored,
                "access_token": new_access,
                "refresh_token": new_refresh,
                "id_token": new_id_token,
                "expires_at": int(time.time()) + max(60, int(value.get("expires_in") or 3600)),
                "scope": " ".join(scopes),
            }
            self.credentials.save(profile_id, updated)
            return updated

    def list_models(self, profile_id: str | None = None) -> list[dict[str, str]]:
        token = self.access_token(profile_id)
        req = request.Request(
            f"{RESOURCE}/models",
            headers={
                "authorization": f"Bearer {token}",
                "accept": "application/json",
                "user-agent": "myth-runtime/0.19",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read()
        except error.HTTPError as exc:
            raise ChatGPTOAuthError(f"ChatGPT model catalog request failed ({exc.code}).") from exc
        except error.URLError as exc:
            raise ChatGPTOAuthError("ChatGPT model catalog could not be reached.") from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ChatGPTOAuthError("ChatGPT model catalog returned invalid JSON.") from exc
        rows = value.get("models") if isinstance(value, dict) else None
        if not isinstance(rows, list) and isinstance(value, dict):
            rows = value.get("data")
        if not isinstance(rows, list):
            raise ChatGPTOAuthError("ChatGPT model catalog has an invalid shape.")
        result = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            if item.get("visibility") not in {None, "list"}:
                continue
            slug = item.get("slug") or item.get("id")
            if not isinstance(slug, str) or not slug:
                continue
            display = item.get("display_name") or slug
            result.append({"slug": slug, "display_name": str(display)})
        return result

    def _revoke_refresh_token(self, refresh_token: str, client_id: str) -> None:
        body=parse.urlencode({"token":refresh_token,"token_type_hint":"refresh_token","client_id":client_id}).encode("utf-8")
        req=request.Request(REVOCATION_ENDPOINT,data=body,method="POST",headers={"content-type":"application/x-www-form-urlencoded","user-agent":"myth-runtime/0.19"})
        try:
            with request.urlopen(req,timeout=self.timeout) as response:
                response.read()
        except error.HTTPError as exc:
            raise ChatGPTOAuthError(f"Remote ChatGPT session revocation failed ({exc.code}).") from exc
        except error.URLError as exc:
            raise ChatGPTOAuthError("Remote ChatGPT session revocation could not be confirmed.") from exc

    def logout(self, profile_id: str | None = None) -> dict[str, Any]:
        profile_id = profile_id or self._active_profile_id()
        if not profile_id:
            return {"signed_out": True, "remote_revoked": True}
        stored = self.credentials.load(profile_id)
        remote_revoked = True
        if stored:
            refresh_token = stored.get("refresh_token")
            client_id = stored.get("client_id")
            if isinstance(refresh_token, str) and refresh_token and isinstance(client_id, str) and client_id:
                try:
                    self._revoke_refresh_token(refresh_token, client_id)
                except ChatGPTOAuthError:
                    remote_revoked = False
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
    """Run one CLI OAuth attempt without exposing callback credentials in logs."""

    result: dict[str, Any] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

        def do_GET(self) -> None:
            parsed = parse.urlparse(self.path)
            if parsed.path != "/auth/callback":
                self.send_response(404)
                self.end_headers()
                return
            try:
                status = manager.complete_callback(parse.parse_qs(parsed.query))
                result["status"] = status
                body = b"Myth is connected to ChatGPT. You can close this window."
                self.send_response(200)
            except Exception as exc:
                result["error"] = exc
                body = b"Myth could not complete ChatGPT sign-in. Return to the terminal for details."
                self.send_response(400)
            self.send_header("content-type", "text/plain; charset=utf-8")
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            done.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 0.5
    redirect_uri = f"http://127.0.0.1:{server.server_port}/auth/callback"
    attempt = manager.begin_login(redirect_uri, profile_id=profile_id)
    if open_browser:
        webbrowser.open(attempt["auth_url"])
    deadline = time.monotonic() + timeout
    try:
        while not done.is_set() and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not done.is_set():
        raise ChatGPTOAuthError("ChatGPT sign-in timed out.")
    if "error" in result:
        raise result["error"]
    return result["status"]
