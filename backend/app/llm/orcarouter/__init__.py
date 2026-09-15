"""OrcaRouter provider integration: credentials, PKCE, discovery, inference."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...config import CACHE_DIR
from .catalog import (
    CAPABILITIES,
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDING,
    CAPABILITY_IMAGE,
    CAPABILITY_RERANK,
    CAPABILITY_VIDEO,
    SEED_SOURCE,
    Catalog,
    ModelRecord,
    VERIFIED_SEED,
    filter_models,
    is_compatible,
    parse_catalog,
    seed_catalog,
    select_models,
)
from .client import (
    KEY_DASHBOARD_URL,
    PROVIDER_API,
    PROVIDER_LABELS,
    PROVIDER_METHOD,
    PROVIDER_OAUTH,
    PROVIDER_IDS,
    REAUTH_HINT,
    OrcaRouterClient,
    ResolvedConfig,
    build_orcarouter_client,
    discovery_for,
    is_orcarouter_provider,
    resolve_orcarouter_config,
)
from .credential_flow import (
    KEY_PREFIX,
    METHOD_API_KEY,
    METHOD_PKCE,
    STATE_NEEDS_REAUTH,
    STATE_OK,
    STATE_UNCONFIGURED,
    Credential,
    CredentialError,
    CredentialFormatError,
    CredentialMissingError,
    CredentialProvider,
    ApiKeyCredentialProvider,
    PkceCredentialProvider,
    LoginCancelled,
    LoginDenied,
    LoginError,
    LoginRateLimited,
    LoginStateMismatch,
    LoginTimeout,
    TerminalReauthError,
    build_authorize_request,
    code_challenge_for,
    get_credential_provider,
    mask_key,
    new_code_verifier,
    new_state,
    normalise_api_key,
    normalise_exchange_code,
    parse_exchange_payload,
    scope_downgraded,
)
from .discovery import DiscoveryError, ModelDiscovery
from .origins import (
    AUTHORIZE_PATH,
    DEFAULT_API_BASE,
    DEFAULT_AUTH_BASE,
    EXCHANGE_PATH,
    OriginError,
    Origins,
    resolve_origins,
    validate_origin,
)
from .pkce import APP_NAME, AUTHORIZATION_TTL_SECONDS, ConnectManager, ConnectSession, ConnectStatus
from .store import CredentialStore

DEFAULT_CREDENTIAL_PATH = Path(CACHE_DIR) / "orcarouter_credentials.json"

_store: Optional[CredentialStore] = None
_manager: Optional[ConnectManager] = None


def get_store() -> CredentialStore:
    global _store
    if _store is None:
        _store = CredentialStore(DEFAULT_CREDENTIAL_PATH)
    return _store


def get_manager() -> ConnectManager:
    global _manager
    if _manager is None:
        _manager = ConnectManager(get_store(), resolve_origins())
    return _manager


def reset_singletons() -> None:
    """Test hook: drop cached store/manager so a fresh path can be injected."""
    global _store, _manager
    _store = None
    _manager = None


__all__ = [
    "APP_NAME",
    "AUTHORIZATION_TTL_SECONDS",
    "AUTHORIZE_PATH",
    "ApiKeyCredentialProvider",
    "CAPABILITIES",
    "CAPABILITY_CHAT",
    "CAPABILITY_EMBEDDING",
    "CAPABILITY_IMAGE",
    "CAPABILITY_RERANK",
    "CAPABILITY_VIDEO",
    "Catalog",
    "ConnectManager",
    "ConnectSession",
    "ConnectStatus",
    "Credential",
    "CredentialError",
    "CredentialFormatError",
    "CredentialMissingError",
    "CredentialProvider",
    "CredentialStore",
    "DEFAULT_API_BASE",
    "DEFAULT_AUTH_BASE",
    "DEFAULT_CREDENTIAL_PATH",
    "DiscoveryError",
    "EXCHANGE_PATH",
    "KEY_DASHBOARD_URL",
    "KEY_PREFIX",
    "LoginCancelled",
    "LoginDenied",
    "LoginError",
    "LoginRateLimited",
    "LoginStateMismatch",
    "LoginTimeout",
    "METHOD_API_KEY",
    "METHOD_PKCE",
    "ModelDiscovery",
    "ModelRecord",
    "OrcaRouterClient",
    "OriginError",
    "Origins",
    "PROVIDER_API",
    "PROVIDER_IDS",
    "PROVIDER_LABELS",
    "PROVIDER_METHOD",
    "PROVIDER_OAUTH",
    "PkceCredentialProvider",
    "REAUTH_HINT",
    "ResolvedConfig",
    "SEED_SOURCE",
    "STATE_NEEDS_REAUTH",
    "STATE_OK",
    "STATE_UNCONFIGURED",
    "TerminalReauthError",
    "VERIFIED_SEED",
    "build_authorize_request",
    "build_orcarouter_client",
    "code_challenge_for",
    "discovery_for",
    "filter_models",
    "get_credential_provider",
    "get_manager",
    "get_store",
    "is_compatible",
    "is_orcarouter_provider",
    "mask_key",
    "new_code_verifier",
    "new_state",
    "normalise_api_key",
    "normalise_exchange_code",
    "parse_catalog",
    "parse_exchange_payload",
    "reset_singletons",
    "resolve_orcarouter_config",
    "resolve_origins",
    "scope_downgraded",
    "seed_catalog",
    "select_models",
    "validate_origin",
]
