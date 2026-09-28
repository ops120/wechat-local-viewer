"""OrcaRouter inference client and provider resolution.

OrcaRouter speaks the OpenAI wire format, so inference reuses the project's
existing :class:`OpenAICompatClient`. What is added here is the credential
boundary: the key comes from the credential seam (pasted key or PKCE), the
model comes from live discovery, and an upstream ``401`` is terminal.

A PKCE-issued key is durable, not refreshable. There is no refresh grant to
call, so a rejected credential is never retried and never silently replaced:
the exact account and generation that made the rejected request is marked
``needs_reauth`` and stays unusable until a new login succeeds.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from ..base import LLMClient
from ..openai_compat import OpenAICompatClient
from .credential_flow import (
    METHOD_API_KEY,
    Credential,
    CredentialError,
    CredentialMissingError,
    STATE_NEEDS_REAUTH,
    TerminalReauthError,
    get_credential_provider,
)
from .discovery import ModelDiscovery
from .net import build_http_client
from .origins import Origins, resolve_origins
from .store import CredentialStore

INFERENCE_TIMEOUT = 60.0

PROVIDER_API = "orcarouter"
PROVIDER_OAUTH = "orcarouter-oauth"
PROVIDER_IDS = (PROVIDER_API, PROVIDER_OAUTH)

PROVIDER_LABELS = {
    PROVIDER_API: "OrcaRouter - API",
    PROVIDER_OAUTH: "OrcaRouter - Auth",
}

# Which credential method each provider id reads from.
PROVIDER_METHOD = {
    PROVIDER_API: METHOD_API_KEY,
    PROVIDER_OAUTH: "pkce",
}

KEY_DASHBOARD_URL = "https://www.orcarouter.ai/console/authorized-apps"
REAUTH_HINT = (
    "OrcaRouter 凭据已被拒绝（401）。请重新连接："
    "在设置中使用 API Key，或重新登录 OrcaRouter 账号。"
)


def is_orcarouter_provider(provider: str) -> bool:
    return (provider or "") in PROVIDER_IDS


@dataclass
class ResolvedConfig:
    """Everything a request needs, with the credential source already erased."""

    base_url: str
    api_key: str
    model: str
    credential: Optional[Credential] = None


class OrcaRouterClient(LLMClient):
    """OpenAI-compatible client bound to the OrcaRouter inference origin."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        origins: Optional[Origins] = None,
        store: Optional[CredentialStore] = None,
        credential: Optional[Credential] = None,
    ):
        self.origins = origins or resolve_origins()
        self.store = store
        self.credential = credential
        if not api_key:
            raise CredentialMissingError("OrcaRouter API Key 不能为空")
        if not model:
            raise ValueError("model 不能为空")
        self.model = model
        self._client = OpenAICompatClient(
            base_url=self.origins.api_base,
            api_key=api_key,
            model=model,
            # Inference gets the same transport policy as the credential and
            # catalog calls: loopback stays direct, and a proxy the host
            # advertises but cannot actually speak is ignored instead of killing
            # the request. Without this the SDK builds its own env-proxy
            # transport, and a host whose proxy only ever served Git fails with
            # an ImportError before a single token streams.
            http_client=build_http_client(INFERENCE_TIMEOUT),
        )

    def stream(self, messages: list[dict]):
        try:
            yield from self._client.stream(messages)
        except Exception as exc:  # noqa: BLE001 - re-raised after 401 classification
            self._classify(exc)
            raise

    def chat(self, messages: list[dict]) -> str:
        try:
            return self._client.chat(messages)
        except Exception as exc:  # noqa: BLE001
            self._classify(exc)
            raise

    def _classify(self, exc: Exception) -> None:
        """Terminal 401 handling: mark exactly one credential generation."""
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(getattr(exc, "response", None), "status_code", None)
        if status != 401:
            return
        if self.store is not None and self.credential is not None:
            self.store.mark_needs_reauth(
                self.credential.account_id,
                self.credential.generation,
                self.credential.method,
            )
        raise TerminalReauthError(REAUTH_HINT) from None


def resolve_orcarouter_config(
    *,
    provider: str,
    model: str,
    store: CredentialStore,
    origins: Optional[Origins] = None,
    fallback_api_key: str = "",
) -> ResolvedConfig:
    """Resolve an OrcaRouter request into (inference base, key, model).

    The credential seam is the only place that knows whether the key was
    pasted or issued by the PKCE flow; everything downstream sees the same
    three fields. ``fallback_api_key`` keeps the project's existing
    ``LLM_API_KEY`` environment habit working for the API-key provider.
    """
    origins = origins or resolve_origins()
    method = PROVIDER_METHOD.get(provider)
    if method is None:
        raise CredentialError(f"未知的 OrcaRouter provider: {provider}")

    provider_impl = get_credential_provider(method, store, origins)
    try:
        credential = provider_impl.acquire()
    except CredentialMissingError:
        env_key = (fallback_api_key or os.getenv("ORCA_API_KEY", "") or "").strip()
        if provider == PROVIDER_API and env_key:
            from .credential_flow import normalise_api_key

            credential = Credential(
                key=normalise_api_key(env_key),
                method=METHOD_API_KEY,
                scope="api",
                source="env",
            )
        else:
            raise

    if credential.state == STATE_NEEDS_REAUTH:
        raise TerminalReauthError(REAUTH_HINT)

    return ResolvedConfig(
        base_url=origins.api_base,
        api_key=credential.key,
        model=model,
        credential=credential,
    )


def build_orcarouter_client(
    config: ResolvedConfig,
    store: CredentialStore,
    origins: Optional[Origins] = None,
) -> OrcaRouterClient:
    return OrcaRouterClient(
        api_key=config.api_key,
        model=config.model,
        origins=origins,
        store=store,
        credential=config.credential,
    )


def discovery_for(store: CredentialStore, origins: Optional[Origins] = None) -> ModelDiscovery:
    """Discovery that prefers the user's key so the list matches their workspace."""
    origins = origins or resolve_origins()
    api_key = ""
    try:
        api_key = get_credential_provider(METHOD_API_KEY, store, origins).acquire().key
    except CredentialError:
        try:
            api_key = get_credential_provider("pkce", store, origins).acquire().key
        except CredentialError:
            api_key = ""
    return ModelDiscovery(origins, api_key=api_key)
