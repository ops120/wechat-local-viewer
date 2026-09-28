"""OrcaRouter endpoints: credentials, PKCE connect, and model discovery.

The API key never enters a browser payload. The frontend receives only
provider labels, masked secrets, credential state, and model metadata; every
request that needs the key is made here, where the key already lives.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..llm.orcarouter import (
    CAPABILITIES,
    KEY_DASHBOARD_URL,
    PROVIDER_API,
    PROVIDER_LABELS,
    PROVIDER_OAUTH,
    REAUTH_HINT,
    Catalog,
    ConnectStatus,
    CredentialError,
    CredentialFormatError,
    CredentialMissingError,
    LoginError,
    LoginStateMismatch,
    TerminalReauthError,
    discovery_for,
    filter_models,
    get_credential_provider,
    get_manager,
    get_store,
    is_orcarouter_provider,
    mask_key,
    normalise_api_key,
    resolve_origins,
)
from ..llm.orcarouter.catalog import CACHE_TTL_SECONDS

router = APIRouter()

_catalog_lock = threading.Lock()
_catalog_cache: Dict[str, Any] = {"catalog": None, "fetched_at": 0.0}


class ApiKeyPayload(BaseModel):
    api_key: str = ""


class ExchangePayload(BaseModel):
    code: str
    attempt: Optional[int] = None
    state: Optional[str] = None


class ActiveMethodPayload(BaseModel):
    method: str


def _provider_entries() -> List[Dict[str, str]]:
    return [
        {"id": PROVIDER_API, "label": PROVIDER_LABELS[PROVIDER_API], "method": "api_key"},
        {"id": PROVIDER_OAUTH, "label": PROVIDER_LABELS[PROVIDER_OAUTH], "method": "pkce"},
    ]


def _credential_summary(store: Any) -> Dict[str, Any]:
    """Redacted per-method status plus a `connected` flag the UI can rely on."""
    status = store.status()
    by_method = {entry["method"]: entry for entry in status["methods"]}
    return {
        # The method a request will actually use, not just the stored preference.
        "active_method": store.resolve_active_method(),
        "api_key": by_method.get("api_key", {}),
        "pkce": by_method.get("pkce", {}),
        "connected": any(entry["configured"] for entry in status["methods"]),
        "needs_reauth": any(entry["state"] == "needs_reauth" for entry in status["methods"]),
    }


def get_catalog(force: bool = False) -> Catalog:
    """Cached live catalog. Used by the selector and by the send-time guard."""
    now = time.time()
    with _catalog_lock:
        cached: Optional[Catalog] = _catalog_cache["catalog"]
        if (
            not force
            and cached is not None
            and (now - float(_catalog_cache["fetched_at"])) < CACHE_TTL_SECONDS
        ):
            return cached
    catalog = discovery_for(get_store(), resolve_origins()).fetch(now=now)
    with _catalog_lock:
        _catalog_cache["catalog"] = catalog
        _catalog_cache["fetched_at"] = now
    return catalog


@router.get("/status")
async def status() -> Dict[str, Any]:
    origins = resolve_origins()
    store = get_store()
    manager = get_manager()
    return {
        "providers": _provider_entries(),
        "credentials": _credential_summary(store),
        "auth_base": origins.auth_base,
        "api_base": origins.api_base,
        "authorize_url": origins.authorize_url,
        "key_dashboard_url": KEY_DASHBOARD_URL,
        "connect": manager.status(),
    }


@router.post("/credentials")
async def set_api_key(payload: ApiKeyPayload) -> Dict[str, Any]:
    """Store a pasted API key. Shape-checked only; validity is proven by use."""
    store = get_store()
    try:
        key = normalise_api_key(payload.api_key)
    except CredentialFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    from ..llm.orcarouter import Credential, METHOD_API_KEY

    account_id = ""
    try:
        provider = get_credential_provider("pkce", store, resolve_origins())
        existing = provider.acquire()
        if existing.key == key:
            # The same key re-entered: keep the account binding, do not mint a
            # new generation, so an in-flight 401 cannot mis-target it.
            account_id = existing.account_id
    except CredentialError:
        account_id = ""

    store.set_credential(
        METHOD_API_KEY,
        Credential(key=key, method=METHOD_API_KEY, account_id=account_id, scope="api"),
    )
    return {"status": "ok", "credentials": _credential_summary(store)}


@router.delete("/credentials/{method}")
async def clear_credential(method: str) -> Dict[str, Any]:
    store = get_store()
    if method not in ("api_key", "pkce"):
        raise HTTPException(status_code=400, detail="未知的认证方式")
    store.clear(method)
    return {"status": "ok", "credentials": _credential_summary(store)}


@router.post("/credentials/active")
async def set_active_method(payload: ActiveMethodPayload) -> Dict[str, Any]:
    store = get_store()
    if payload.method not in ("api_key", "pkce"):
        raise HTTPException(status_code=400, detail="未知的认证方式")
    store.set_active_method(payload.method)
    return {"status": "ok", "credentials": _credential_summary(store)}


@router.get("/models")
async def models(capability: str = "chat", modality: Optional[str] = None) -> Dict[str, Any]:
    """Capability-filtered options for one entry point.

    `force=true` (via /models/refresh) bypasses the cache; otherwise the
    cached catalog is reused so a selector does not hit the network per render.
    """
    if capability not in CAPABILITIES:
        raise HTTPException(status_code=400, detail=f"未知的能力: {capability}")
    catalog = get_catalog()
    filtered = filter_models(catalog.models, capability, modality)
    return {
        "capability": capability,
        "modality": modality,
        "source": catalog.source,
        "degraded": catalog.degraded,
        "detail": catalog.detail,
        "count": len(filtered),
        "options": [record.to_dict() for record in filtered],
    }


@router.post("/models/refresh")
async def refresh_models(capability: str = "chat", modality: Optional[str] = None) -> Dict[str, Any]:
    if capability not in CAPABILITIES:
        raise HTTPException(status_code=400, detail=f"未知的能力: {capability}")
    catalog = get_catalog(force=True)
    filtered = filter_models(catalog.models, capability, modality)
    return {
        "capability": capability,
        "modality": modality,
        "source": catalog.source,
        "degraded": catalog.degraded,
        "detail": catalog.detail,
        "count": len(filtered),
        "options": [record.to_dict() for record in filtered],
    }


# --------------------------------------------------------------------------
# PKCE connect flow
# --------------------------------------------------------------------------


@router.post("/connect/start")
async def connect_start() -> Dict[str, Any]:
    manager = get_manager()
    session = manager.start()
    return session.public()


@router.get("/connect/status")
async def connect_status() -> Dict[str, Any]:
    manager = get_manager()
    status_payload = manager.status()
    status_payload["credentials"] = _credential_summary(get_store())
    return status_payload


@router.post("/connect/exchange")
async def connect_exchange(payload: ExchangePayload) -> Dict[str, Any]:
    manager = get_manager()
    try:
        credential = manager.exchange(payload.code, attempt=payload.attempt, state=payload.state)
    except LoginStateMismatch as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except LoginError as exc:
        code = getattr(exc, "code", "login_error")
        http_status = 429 if code == "rate_limited" else 400
        raise HTTPException(status_code=http_status, detail={"code": code, "message": str(exc)}) from None
    return {
        "status": "ok",
        "credential": {
            "method": credential.method,
            "account_id": credential.account_id,
            "scope": credential.scope,
            "secret_masked": mask_key(credential.key),
        },
        "credentials": _credential_summary(get_store()),
    }


@router.post("/connect/cancel")
async def connect_cancel() -> Dict[str, Any]:
    manager = get_manager()
    cancelled = manager.cancel()
    return {"status": "ok", "cancelled": cancelled}


# --------------------------------------------------------------------------
# Inference helper used by /api/llm/chat
# --------------------------------------------------------------------------


def prepare_orcarouter_provider(provider: str, model: str, fallback_api_key: str = ""):
    """Resolve the credential seam into a ready client. Raises HTTPException."""
    from ..llm.orcarouter import build_orcarouter_client, resolve_orcarouter_config

    store = get_store()
    origins = resolve_origins()
    try:
        config = resolve_orcarouter_config(
            provider=provider,
            model=model,
            store=store,
            origins=origins,
            fallback_api_key=fallback_api_key,
        )
    except CredentialMissingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except TerminalReauthError as exc:
        raise HTTPException(status_code=401, detail=REAUTH_HINT) from None
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    catalog = get_catalog()
    if not catalog.degraded:
        allowed = {record.id for record in filter_models(catalog.models, "chat")}
        if model not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"模型 {model} 不在当前 OrcaRouter 文本模型目录中，请在设置中重新选择",
            )

    return build_orcarouter_client(config, store, origins), config


def provider_is_orcarouter(provider: Optional[str]) -> bool:
    return is_orcarouter_provider(provider or "")


__all__ = ["router", "get_catalog", "prepare_orcarouter_provider", "ConnectStatus"]
