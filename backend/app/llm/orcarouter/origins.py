"""OrcaRouter origin resolution.

Authentication and inference live on two different public origins:

* auth + code exchange: ``https://www.orcarouter.ai``
* inference + model discovery: ``https://api.orcarouter.ai/v1``

The two must never be derived from one another by swapping a hostname or by
blindly appending ``/v1`` — ``https://api.orcarouter.ai/v1/auth/keys`` is a 404.
Self-hosted deployments may serve both roles from one origin, so a shared
``ORCA_BASE_URL`` fallback is supported, with explicit ``ORCA_AUTH_BASE_URL`` /
``ORCA_API_BASE_URL`` overrides taking precedence.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_AUTH_BASE = "https://www.orcarouter.ai"
DEFAULT_API_BASE = "https://api.orcarouter.ai/v1"

# Fixed, documented paths (see the integration guide's endpoint table).
AUTHORIZE_PATH = "/auth"
EXCHANGE_PATH = "/api/v1/auth/keys"
DEVICE_CODE_PATH = "/api/v1/auth/device/code"
DEVICE_TOKEN_PATH = "/api/v1/auth/device/token"
MODELS_PATH = "/models"

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


class OriginError(ValueError):
    """A configured origin is unusable (bad scheme, credentials, or fragment)."""


@dataclass(frozen=True)
class Origins:
    auth_base: str
    api_base: str

    @property
    def authorize_url(self) -> str:
        return self.auth_base + AUTHORIZE_PATH

    @property
    def exchange_url(self) -> str:
        return self.auth_base + EXCHANGE_PATH

    @property
    def device_code_url(self) -> str:
        return self.auth_base + DEVICE_CODE_PATH

    @property
    def device_token_url(self) -> str:
        return self.auth_base + DEVICE_TOKEN_PATH

    @property
    def models_url(self) -> str:
        return self.api_base.rstrip("/") + MODELS_PATH


def is_loopback(host: str) -> bool:
    return host.lower() in _LOOPBACK_HOSTS


def validate_origin(origin: str, *, name: str) -> str:
    """Remote origins must be HTTPS; plain HTTP is allowed only on loopback."""
    if not origin or not origin.strip():
        raise OriginError(f"{name} 不能为空")
    value = origin.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https"):
        raise OriginError(f"{name} 必须是 http(s) URL: {value}")
    if not parts.hostname:
        raise OriginError(f"{name} 缺少主机名: {value}")
    if parts.username or parts.password:
        raise OriginError(f"{name} 不能包含用户信息: {value}")
    if parts.fragment:
        raise OriginError(f"{name} 不能包含 fragment: {value}")
    if parts.scheme == "http" and not is_loopback(parts.hostname):
        raise OriginError(f"{name} 远程 origin 必须使用 HTTPS: {value}")
    return value


def resolve_origins(env: "os._Environ[str] | None" = None) -> Origins:
    """Resolve auth/inference origins. Explicit overrides win over the shared base."""
    env = os.environ if env is None else env
    shared = (env.get("ORCA_BASE_URL") or "").strip()
    auth = (env.get("ORCA_AUTH_BASE_URL") or "").strip() or shared or DEFAULT_AUTH_BASE
    api = (env.get("ORCA_API_BASE_URL") or "").strip() or shared or DEFAULT_API_BASE
    return Origins(
        auth_base=validate_origin(auth, name="ORCA_AUTH_BASE_URL"),
        api_base=validate_origin(api, name="ORCA_API_BASE_URL"),
    )
