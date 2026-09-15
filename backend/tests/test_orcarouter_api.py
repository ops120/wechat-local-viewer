"""End-to-end tests through the project's own OrcaRouter HTTP endpoints.

These drive the real FastAPI routes that the settings panel calls, so the
paths exercised are the paths shipped: credential storage, both adapters, the
connect flow, model options, and the 401 classification.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import orcarouter as orca_api
from app.llm.orcarouter import (
    Catalog,
    CredentialStore,
    METHOD_API_KEY,
    METHOD_PKCE,
    OrcaRouterClient,
    TerminalReauthError,
    get_credential_provider,
    parse_catalog,
    resolve_origins,
    seed_catalog,
)

FAKE_KEY = "sk-orca-" + "d" * 32
FAKE_PKCE_KEY = "sk-orca-" + "e" * 32

FIXTURE = {
    "data": [
        {
            "id": "acme/text-only",
            "name": "Acme Text Only",
            "context_length": 128000,
            "supported_endpoint_types": ["openai"],
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        },
        {
            "id": "acme/vision-chat",
            "name": "Acme Vision Chat",
            "supported_endpoint_types": ["openai"],
            "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
        },
        {
            "id": "acme/image-xl",
            "name": "Acme Image XL",
            "supported_endpoint_types": ["image-generation"],
            "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]},
        },
    ]
}


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    store = CredentialStore(tmp_path / "creds.json")
    monkeypatch.setattr(orca_api, "get_store", lambda: store)

    app = FastAPI()
    app.include_router(orca_api.router, prefix="/api/orcarouter")
    client = TestClient(app)
    client.store = store  # type: ignore[attr-defined]
    return client


@pytest.fixture()
def live_catalog(monkeypatch):
    catalog = Catalog(models=parse_catalog(FIXTURE), source="live", degraded=False)
    monkeypatch.setattr(orca_api, "get_catalog", lambda force=False: catalog)
    monkeypatch.setattr(orca_api, "get_catalog", lambda force=False: catalog, raising=True)
    return catalog


def test_status_exposes_two_providers_and_masked_secrets(app_client):
    payload = app_client.get("/api/orcarouter/status").json()
    ids = [p["id"] for p in payload["providers"]]
    assert ids == ["orcarouter", "orcarouter-oauth"]
    labels = {p["id"]: p["label"] for p in payload["providers"]}
    assert labels["orcarouter"] == "OrcaRouter - API"
    assert labels["orcarouter-oauth"] == "OrcaRouter - Auth"
    # Status is safe for a browser: masked only, and it names both origins.
    assert payload["auth_base"] == "https://www.orcarouter.ai"
    assert payload["api_base"] == "https://api.orcarouter.ai/v1"
    assert payload["credentials"]["connected"] is False
    assert FAKE_KEY not in json.dumps(payload)


def test_api_key_is_stored_masked_and_never_returned(app_client):
    response = app_client.post("/api/orcarouter/credentials", json={"api_key": FAKE_KEY})
    assert response.status_code == 200
    body = response.json()
    assert body["credentials"]["api_key"]["configured"] is True
    assert body["credentials"]["connected"] is True
    # The raw key is not echoed back and is not in the store's public view.
    assert FAKE_KEY not in response.text
    assert body["credentials"]["api_key"]["secret_masked"].endswith(FAKE_KEY[-4:])
    assert app_client.store.get_credential(METHOD_API_KEY)["key"] == FAKE_KEY


def test_api_key_format_errors_are_reported_to_the_user(app_client):
    response = app_client.post("/api/orcarouter/credentials", json={"api_key": "nope"})
    assert response.status_code == 400
    assert "sk-orca-" in response.json()["detail"]


def test_api_key_can_be_cleared(app_client):
    app_client.post("/api/orcarouter/credentials", json={"api_key": FAKE_KEY})
    response = app_client.request("DELETE", "/api/orcarouter/credentials/api_key")
    assert response.status_code == 200
    assert response.json()["credentials"]["connected"] is False
    assert app_client.store.get_credential(METHOD_API_KEY) is None


def test_both_adapters_resolve_to_the_same_provider_path(app_client, live_catalog):
    """Only one credential result shape reaches the provider, whichever adapter ran."""
    origins = resolve_origins({})

    app_client.post("/api/orcarouter/credentials", json={"api_key": FAKE_KEY})
    app_client.store.set_credential(
        METHOD_PKCE,
        __import__("app.llm.orcarouter", fromlist=["Credential"]).Credential(
            key=FAKE_PKCE_KEY, method=METHOD_PKCE, account_id="42", scope="api"
        ),
    )

    from_api = get_credential_provider(METHOD_API_KEY, app_client.store, origins).acquire()
    from_pkce = get_credential_provider(METHOD_PKCE, app_client.store, origins).acquire()

    client_api = OrcaRouterClient(from_api.key, "acme/text-only", origins=origins)
    client_pkce = OrcaRouterClient(from_pkce.key, "acme/text-only", origins=origins)

    # Identical inference origin and identical model namespace; the credential
    # source is invisible downstream.
    assert client_api.origins.api_base == client_pkce.origins.api_base
    assert client_api.origins.api_base == "https://api.orcarouter.ai/v1"
    assert client_api.model == client_pkce.model
    assert client_api._client.base_url == client_pkce._client.base_url


def test_model_options_come_from_the_catalog_not_a_free_text_field(app_client, live_catalog):
    payload = app_client.get("/api/orcarouter/models?capability=chat").json()
    option_ids = [o["id"] for o in payload["options"]]
    assert option_ids == ["acme/text-only", "acme/vision-chat"]
    assert payload["source"] == "live"
    assert payload["degraded"] is False
    assert payload["count"] == len(payload["options"])


def test_image_attachment_filters_chat_options(app_client, live_catalog):
    text_only = app_client.get("/api/orcarouter/models?capability=chat").json()
    with_image = app_client.get("/api/orcarouter/models?capability=chat&modality=image").json()

    assert [o["id"] for o in with_image["options"]] == ["acme/vision-chat"]
    # The text-only chat model is no longer offered once an image is attached.
    assert "acme/text-only" not in [o["id"] for o in with_image["options"]]
    assert len(with_image["options"]) < len(text_only["options"])


def test_non_chat_capabilities_match_their_own_routes(app_client, live_catalog):
    image = app_client.get("/api/orcarouter/models?capability=image").json()
    assert [o["id"] for o in image["options"]] == ["acme/image-xl"]
    embedding = app_client.get("/api/orcarouter/models?capability=embedding").json()
    assert embedding["options"] == []


def test_unknown_capability_is_rejected(app_client):
    assert app_client.get("/api/orcarouter/models?capability=telepathy").status_code == 400


def test_catalog_outage_serves_only_the_verified_seed(app_client, monkeypatch):
    degraded = Catalog(
        models=seed_catalog(), source="seed", degraded=True, detail="模型目录请求失败"
    )
    monkeypatch.setattr(orca_api, "get_catalog", lambda force=False: degraded)

    payload = app_client.get("/api/orcarouter/models?capability=chat").json()
    assert payload["degraded"] is True
    assert payload["source"] == "seed"
    assert [o["id"] for o in payload["options"]] == [
        "openai/gpt-5.5",
        "anthropic/claude-opus-4.8",
        "google/gemini-3.5-flash",
        "deepseek/deepseek-v4-pro",
        "orcarouter/auto",
    ]
    # Every option is a real catalog id with its metadata intact — not an
    # unverified example, and not a placeholder for free text.
    gpt = next(o for o in payload["options"] if o["id"] == "openai/gpt-5.5")
    assert gpt["reasoning_efforts"] == ["low", "medium", "high", "xhigh"]
    assert gpt["source"] == "verified-seed"


def test_connect_start_returns_the_auth_origin_url(app_client, monkeypatch):
    class FakeManager:
        attempt = 1

        def start(self, scope="api"):
            from app.llm.orcarouter import ConnectStatus

            class Session:
                def public(self):
                    return {
                        "attempt": 1,
                        "status": ConnectStatus.PENDING.value,
                        "authorize_url": "https://www.orcarouter.ai/auth?callback_url=oob&code_challenge_method=S256",
                        "app_name": "WeChat Local Viewer",
                        "scope": "api",
                    }

            return Session()

        def status(self):
            return {"attempt": 1, "status": "pending"}

        def cancel(self):
            return True

    monkeypatch.setattr(orca_api, "get_manager", lambda: FakeManager())
    payload = app_client.post("/api/orcarouter/connect/start", json={}).json()
    assert payload["authorize_url"].startswith("https://www.orcarouter.ai/auth")
    assert "callback_url=oob" in payload["authorize_url"]
    assert "api.orcarouter.ai" not in payload["authorize_url"]
    # No verifier and no key anywhere in the payload a browser receives.
    assert "code_verifier" not in json.dumps(payload)


def test_connect_exchange_surfaces_errors_without_leaking(app_client, monkeypatch):
    from app.llm.orcarouter import LoginError

    class FailingManager:
        def exchange(self, code, attempt=None, state=None):
            raise LoginError("code_rejected", "授权码无效 (403)：已过期或已被使用")

    monkeypatch.setattr(orca_api, "get_manager", lambda: FailingManager())
    response = app_client.post("/api/orcarouter/connect/exchange", json={"code": "x", "attempt": 1})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "code_rejected"
    assert "code_verifier" not in response.text


def test_connect_exchange_rate_limit_returns_429(app_client, monkeypatch):
    from app.llm.orcarouter import LoginRateLimited

    class LimitedManager:
        def exchange(self, code, attempt=None, state=None):
            raise LoginRateLimited()

    monkeypatch.setattr(orca_api, "get_manager", lambda: LimitedManager())
    response = app_client.post("/api/orcarouter/connect/exchange", json={"code": "x", "attempt": 1})
    assert response.status_code == 429


def test_cancel_endpoint_releases_the_attempt(app_client, monkeypatch):
    calls = []

    class Manager:
        def cancel(self):
            calls.append(1)
            return True

    monkeypatch.setattr(orca_api, "get_manager", lambda: Manager())
    assert app_client.post("/api/orcarouter/connect/cancel", json={}).json()["cancelled"] is True
    assert calls == [1]


def test_revoked_key_marks_needs_reauth_without_refresh(tmp_path):
    """A 401 is terminal: the exact generation is marked, nothing is refreshed."""
    store = CredentialStore(tmp_path / "creds.json")
    origins = resolve_origins({})
    from app.llm.orcarouter import Credential

    store.set_credential(
        METHOD_PKCE, Credential(key=FAKE_PKCE_KEY, method=METHOD_PKCE, account_id="9", scope="api")
    )
    credential = get_credential_provider(METHOD_PKCE, store, origins).acquire()

    class UnauthorizedClient:
        base_url = origins.api_base

        def chat(self, messages):
            request = httpx.Request("POST", f"{origins.api_base}/chat/completions")
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError("401", request=request, response=response)

    client = OrcaRouterClient(FAKE_PKCE_KEY, "acme/text-only", origins=origins, store=store, credential=credential)
    client._client = UnauthorizedClient()

    with pytest.raises(TerminalReauthError):
        client.chat([{"role": "user", "content": "hi"}])

    entry = store.get_credential(METHOD_PKCE)
    assert entry["state"] == "needs_reauth"
    # The secret survives so a transient misclassification is recoverable.
    assert entry["key"] == FAKE_PKCE_KEY
    assert entry["generation"] == credential.generation


def test_late_401_does_not_pollute_a_reconnected_credential(tmp_path):
    store = CredentialStore(tmp_path / "creds.json")
    origins = resolve_origins({})
    from app.llm.orcarouter import Credential

    store.set_credential(
        METHOD_PKCE, Credential(key=FAKE_PKCE_KEY, method=METHOD_PKCE, account_id="9", scope="api")
    )
    stale = get_credential_provider(METHOD_PKCE, store, origins).acquire()

    # The user reconnects: a new generation is stored.
    store.set_credential(
        METHOD_PKCE, Credential(key=FAKE_KEY, method=METHOD_PKCE, account_id="9", scope="api")
    )

    class UnauthorizedClient:
        def chat(self, messages):
            request = httpx.Request("POST", "https://api.orcarouter.ai/v1/chat/completions")
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError("401", request=request, response=response)

    client = OrcaRouterClient(FAKE_PKCE_KEY, "acme/text-only", origins=origins, store=store, credential=stale)
    client._client = UnauthorizedClient()
    with pytest.raises(TerminalReauthError):
        client.chat([{"role": "user", "content": "hi"}])

    # The freshly reauthorized credential is untouched.
    assert store.get_credential(METHOD_PKCE)["state"] == "ok"
    assert store.get_credential(METHOD_PKCE)["key"] == FAKE_KEY


def test_needs_reauth_credential_is_refused_at_request_time(app_client):
    from app.llm.orcarouter import Credential
    from app.llm.orcarouter.client import resolve_orcarouter_config
    from app.llm.orcarouter import TerminalReauthError

    store = app_client.store
    store.set_credential(
        METHOD_API_KEY, Credential(key=FAKE_KEY, method=METHOD_API_KEY, scope="api")
    )
    entry = store.get_credential(METHOD_API_KEY)
    store.mark_needs_reauth("", entry["generation"], METHOD_API_KEY)

    with pytest.raises(TerminalReauthError):
        resolve_orcarouter_config(
            provider="orcarouter", model="acme/text-only", store=store, origins=resolve_origins({})
        )


def test_api_key_provider_falls_back_to_the_environment_key(app_client, monkeypatch):
    from app.llm.orcarouter import Credential
    from app.llm.orcarouter.client import resolve_orcarouter_config

    monkeypatch.setenv("ORCA_API_KEY", FAKE_KEY)
    config = resolve_orcarouter_config(
        provider="orcarouter",
        model="acme/text-only",
        store=app_client.store,
        origins=resolve_origins({}),
    )
    assert config.api_key == FAKE_KEY
    assert config.base_url == "https://api.orcarouter.ai/v1"
    assert config.credential.source == "env"
    assert isinstance(config.credential, Credential)


def test_pkce_provider_never_falls_back_to_an_environment_key(app_client, monkeypatch):
    from app.llm.orcarouter import CredentialMissingError
    from app.llm.orcarouter.client import resolve_orcarouter_config

    monkeypatch.setenv("ORCA_API_KEY", FAKE_KEY)
    # The Auth provider must not silently pick up a pasted/env key: that would
    # make the two choices indistinguishable.
    with pytest.raises(CredentialMissingError):
        resolve_orcarouter_config(
            provider="orcarouter-oauth",
            model="acme/text-only",
            store=app_client.store,
            origins=resolve_origins({}),
        )


def test_auth_overrides_take_precedence_over_the_shared_base():
    origins = resolve_origins(
        {
            "ORCA_BASE_URL": "https://self.example.com",
            "ORCA_AUTH_BASE_URL": "https://auth.example.com",
            "ORCA_API_BASE_URL": "https://api.example.com/v1",
        }
    )
    assert origins.auth_base == "https://auth.example.com"
    assert origins.api_base == "https://api.example.com/v1"
    assert origins.exchange_url == "https://auth.example.com/api/v1/auth/keys"
    assert origins.models_url == "https://api.example.com/v1/models"


def test_shared_self_hosted_base_serves_both_roles():
    origins = resolve_origins({"ORCA_BASE_URL": "https://self.example.com"})
    assert origins.auth_base == "https://self.example.com"
    assert origins.api_base == "https://self.example.com"
    assert origins.exchange_url == "https://self.example.com/api/v1/auth/keys"


def test_remote_http_origin_is_refused_but_loopback_is_allowed():
    from app.llm.orcarouter import OriginError, validate_origin

    with pytest.raises(OriginError):
        validate_origin("http://self.example.com", name="ORCA_AUTH_BASE_URL")
    assert validate_origin("http://127.0.0.1:18787", name="ORCA_AUTH_BASE_URL")
    assert validate_origin("http://localhost:9000", name="ORCA_API_BASE_URL")
    with pytest.raises(OriginError):
        validate_origin("https://user:pass@self.example.com", name="ORCA_API_BASE_URL")
    with pytest.raises(OriginError):
        validate_origin("ftp://self.example.com", name="ORCA_API_BASE_URL")


def test_orcarouter_inference_uses_the_project_transport_policy(monkeypatch):
    """Inference must not be at the mercy of the host's proxy configuration.

    The SDK builds its own env-proxy transport when handed nothing, so on a host
    advertising a proxy it cannot speak (a SOCKS proxy without socksio — the
    common "only Git uses it" setup) request construction raises before any
    token streams, and routing through a proxy it *can* speak would send the
    credential off-host. The OrcaRouter client hands the SDK the same client
    net.build_http_client() builds, so both properties hold.
    """
    from app.llm.orcarouter import net

    monkeypatch.setattr(
        net.importlib.util, "find_spec", lambda name: None if name == "socksio" else object()
    )
    for name in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "socks5://127.0.0.1:1080")

    origins = resolve_origins({})
    client = OrcaRouterClient(FAKE_KEY, "acme/text-only", origins=origins)
    transport = client._client.client._client._transport
    assert not hasattr(transport, "_proxy_url"), "inference must not be proxied"
    assert net._proxies_are_usable() is False


def test_generic_openai_provider_keeps_the_sdk_default_transport(monkeypatch):
    """The pre-existing OpenAI-compatible provider is untouched by this change.

    Asserted at the seam rather than by building a client: the point is that
    omitting http_client passes no http_client argument to the SDK, so the
    provider keeps whatever transport the SDK chose before. Constructing one
    here would instead assert whatever the *host's* proxy configuration happens
    to allow, which is exactly the coupling this parameter exists to avoid.
    """
    import openai

    from app.llm.openai_compat import OpenAICompatClient

    seen: list[dict] = []
    sentinel = object()

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return sentinel

    monkeypatch.setattr(openai, "OpenAI", spy)
    client = OpenAICompatClient(
        base_url="https://example.invalid/v1", api_key="sk-generic", model="m"
    )
    assert seen, "the SDK was never constructed"
    assert "http_client" not in seen[0]
    assert client.client is sentinel
