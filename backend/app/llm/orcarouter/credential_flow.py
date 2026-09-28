"""OrcaRouter credential acquisition seam.

Both ways of getting an OrcaRouter credential end in the *same* artifact: an
``sk-orca-…`` API key. That is the only thing the provider layer downstream
ever sees, so provider requests and model discovery never branch on how the
key was obtained.

Two adapters implement :class:`CredentialProvider`:

* :class:`ApiKeyCredentialProvider` — the user pastes an existing key.
* :class:`PkceCredentialProvider`    — OAuth 2.0 + PKCE issues a fresh key.

A PKCE-issued key is a *durable* key, not a refresh token: there is no refresh
endpoint, so it is reused until OrcaRouter revokes it, and a relay ``401`` is a
terminal reauthentication requirement rather than something to retry.
"""

from __future__ import annotations

import hashlib
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlencode

from .origins import Origins

# Credential methods. These are identifiers, not secrets.
METHOD_API_KEY = "api_key"
METHOD_PKCE = "pkce"

# Credential lifecycle states.
STATE_UNCONFIGURED = "unconfigured"
STATE_OK = "ok"
STATE_NEEDS_REAUTH = "needs_reauth"

MAX_KEY_LENGTH = 512
KEY_PREFIX = "sk-orca-"


class CredentialError(Exception):
    """Base class for credential failures that are safe to show to the user."""

    code = "credential_error"


class CredentialFormatError(CredentialError):
    code = "invalid_format"


class CredentialMissingError(CredentialError):
    code = "missing_credential"


class TerminalReauthError(CredentialError):
    """The upstream rejected this exact credential generation with 401."""

    code = "needs_reauth"


class LoginError(CredentialError):
    """A PKCE attempt ended without a usable key."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class LoginDenied(LoginError):
    def __init__(self, message: str = "授权被拒绝"):
        super().__init__("access_denied", message)


class LoginStateMismatch(LoginError):
    def __init__(self, message: str = "state 校验失败"):
        super().__init__("state_mismatch", message)


class LoginTimeout(LoginError):
    def __init__(self, message: str = "授权超时"):
        super().__init__("timeout", message)


class LoginCancelled(LoginError):
    def __init__(self, message: str = "授权已取消"):
        super().__init__("cancelled", message)


class LoginRateLimited(LoginError):
    def __init__(self, message: str = "授权请求过于频繁"):
        super().__init__("rate_limited", message)


@dataclass(frozen=True)
class Credential:
    """The single artifact both adapters produce."""

    key: str
    method: str
    account_id: str = ""
    scope: str = ""
    generation: int = 1
    state: str = STATE_OK
    source: str = field(default="", compare=False)

    @property
    def is_usable(self) -> bool:
        return self.state == STATE_OK and bool(self.key)

    def masked(self) -> str:
        """Never return the raw key to a UI/API surface that only needs a hint."""
        return mask_key(self.key)


def mask_key(key: str) -> str:
    """A hint, never the credential. Short keys are redacted entirely."""
    if not key:
        return ""
    if len(key) <= 16:
        return KEY_PREFIX + "…"
    return f"{key[:11]}…{key[-4:]}"


def normalise_api_key(raw: str) -> str:
    """Trim and reject obvious input mistakes.

    An ``sk-orca-`` prefix is a shape check only — it is not proof that the key
    is valid. Validity is established by the first real request, because
    OrcaRouter exposes no non-billing validation endpoint.
    """
    key = (raw or "").strip().strip('"').strip("'")
    if not key:
        raise CredentialFormatError("API Key 不能为空")
    if any(ch.isspace() for ch in key) or len(key) > MAX_KEY_LENGTH:
        raise CredentialFormatError("API Key 含空白字符或长度异常")
    if not key.startswith(KEY_PREFIX):
        raise CredentialFormatError("API Key 应以 sk-orca- 开头")
    return key


class CredentialProvider(ABC):
    """Read side of the credential seam. Both adapters satisfy it."""

    method: str = ""

    def __init__(self, store: "object", origins: Origins):
        self.store = store
        self.origins = origins

    @abstractmethod
    def acquire(self) -> Credential:
        """Return a usable credential or raise CredentialError."""

    def invalidate(self, credential: Credential) -> None:
        """Mark a rejected credential generation as needing reauthentication.

        Only the exact account/generation that made the rejected request is
        touched, so a late failure from an old request can never mark a freshly
        reauthorized credential as broken.
        """
        mark_needs_reauth = getattr(self.store, "mark_needs_reauth", None)
        if callable(mark_needs_reauth):
            mark_needs_reauth(
                credential.account_id, credential.generation, credential.method
            )


class ApiKeyCredentialProvider(CredentialProvider):
    """Adapter 1: the user pastes an ``sk-orca-…`` key."""

    method = METHOD_API_KEY

    def acquire(self) -> Credential:
        pkey = self.store.get_credential(METHOD_API_KEY)
        if not pkey or not pkey.get("key"):
            raise CredentialMissingError("未配置 OrcaRouter API Key")
        key = normalise_api_key(pkey["key"])
        return Credential(
            key=key,
            method=METHOD_API_KEY,
            account_id=pkey.get("account_id") or "",
            scope=pkey.get("scope") or "api",
            generation=int(pkey.get("generation") or 1),
            state=pkey.get("state") or STATE_OK,
            source="stored",
        )


class PkceCredentialProvider(CredentialProvider):
    """Adapter 2: a PKCE connect flow issued the key."""

    method = METHOD_PKCE

    def acquire(self) -> Credential:
        pkey = self.store.get_credential(METHOD_PKCE)
        if not pkey or not pkey.get("key"):
            raise CredentialMissingError("尚未通过 OrcaRouter 账号登录")
        key = normalise_api_key(pkey["key"])
        return Credential(
            key=key,
            method=METHOD_PKCE,
            account_id=pkey.get("account_id") or "",
            scope=pkey.get("scope") or "api",
            generation=int(pkey.get("generation") or 1),
            state=pkey.get("state") or STATE_OK,
            source="pkce",
        )


def get_credential_provider(method: str, store: "object", origins: Origins) -> CredentialProvider:
    """Resolve an adapter by method id. Provider code uses this, never the reverse."""
    if method == METHOD_PKCE:
        return PkceCredentialProvider(store, origins)
    if method == METHOD_API_KEY:
        return ApiKeyCredentialProvider(store, origins)
    raise CredentialError(f"未知的认证方式: {method}")


# --------------------------------------------------------------------------
# PKCE primitives
# --------------------------------------------------------------------------


def _b64url(raw: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def new_code_verifier() -> str:
    """Fresh, high-entropy verifier from a cryptographic RNG, per attempt."""
    return _b64url(secrets.token_bytes(32))


def code_challenge_for(verifier: str) -> str:
    """``base64url(sha256(verifier))`` with no padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _b64url(digest)


def new_state() -> str:
    return _b64url(secrets.token_bytes(16))


def constant_time_equals(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


@dataclass
class AuthorizeRequest:
    """Everything the consent screen needs. The verifier is deliberately absent."""

    url: str
    state: str
    verifier: str
    challenge: str
    method: str = "S256"


def build_authorize_request(
    origins: Origins,
    *,
    app_name: str = "WeChat Local Viewer",
    scope: str = "api",
    callback_url: str = "oob",
    verifier: Optional[str] = None,
    state: Optional[str] = None,
) -> AuthorizeRequest:
    """Build the authorize URL.

    ``callback_url=oob`` asks for out-of-band delivery explicitly rather than
    leaving the mode to be guessed at. S256 is always sent: even with a real
    callback the user may pick "show me a code" on the consent screen, and a
    displayed code must only be redeemable by the process holding the verifier.
    """
    if scope not in ("api", "connector"):
        raise LoginError("invalid_scope", f"不支持的 scope: {scope}")
    verifier = verifier or new_code_verifier()
    challenge = code_challenge_for(verifier)
    state = state or new_state()
    query = urlencode(
        {
            "callback_url": callback_url,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "app_name": app_name,
            "scope": scope,
        }
    )
    return AuthorizeRequest(
        url=f"{origins.authorize_url}?{query}",
        state=state,
        verifier=verifier,
        challenge=challenge,
    )


def normalise_exchange_code(raw: str) -> str:
    """Trim a pasted code. Codes are single-use with a 10 minute TTL."""
    code = (raw or "").strip()
    if not code:
        raise LoginError("missing_code", "授权码不能为空")
    if len(code) > 512 or any(ch.isspace() for ch in code):
        raise LoginError("invalid_code", "授权码格式不正确")
    return code


def parse_exchange_payload(payload: object, *, requested_scope: str) -> Credential:
    """Read the exchange response.

    ``scope`` in the response is what was *granted*, not what was asked for, so
    it is read back rather than assumed. A narrower grant is surfaced by the
    caller as a warning; it never silently becomes the requested scope.
    """
    if not isinstance(payload, dict):
        raise LoginError("bad_response", "授权服务返回了无法解析的响应")
    key = payload.get("key")
    if not isinstance(key, str) or not key:
        raise LoginError("bad_response", "授权服务未返回 API Key")
    granted = payload.get("scope") or ""
    if granted not in ("api", "connector"):
        raise LoginError("bad_scope", f"授权服务返回了未知的 scope: {granted}")
    user_id = payload.get("user_id")
    return Credential(
        key=key,
        method=METHOD_PKCE,
        account_id=str(user_id) if user_id is not None else "",
        scope=granted,
        state=STATE_OK,
        source="pkce",
    )


def scope_downgraded(credential: Credential, requested_scope: str) -> bool:
    """True when the granted scope is narrower than what was requested."""
    if credential.scope == requested_scope:
        return False
    if requested_scope == "connector" and credential.scope == "api":
        return True
    return True
