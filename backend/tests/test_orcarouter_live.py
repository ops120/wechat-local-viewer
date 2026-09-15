"""Live end-to-end checks against the real OrcaRouter service.

These run only when ``ORCAROUTER_API_KEY`` is present in the environment; with
no key the whole module is skipped, so the default suite stays offline and
deterministic. Nothing here writes the key anywhere: the credential goes
straight into a temporary store under pytest's tmp_path.
"""

from __future__ import annotations

import os

import pytest

from app.llm.orcarouter import (
    CAPABILITY_CHAT,
    METHOD_API_KEY,
    Catalog,
    Credential,
    CredentialStore,
    ModelDiscovery,
    build_orcarouter_client,
    filter_models,
    resolve_orcarouter_config,
    resolve_origins,
)

LIVE_KEY = os.getenv("ORCAROUTER_API_KEY", "").strip()
pytestmark = pytest.mark.skipif(
    not LIVE_KEY, reason="ORCAROUTER_API_KEY 未设置：跳过真实网络检查"
)


@pytest.fixture()
def live_store(tmp_path):
    store = CredentialStore(tmp_path / "orcarouter_credentials.json")
    store.set_credential(
        METHOD_API_KEY,
        Credential(key=LIVE_KEY, method=METHOD_API_KEY, scope="api"),
    )
    return store


@pytest.fixture(scope="module")
def live_catalog():
    origins = resolve_origins({})
    discovery = ModelDiscovery(origins, api_key=LIVE_KEY)
    return discovery.fetch()


def test_live_model_catalog_is_reachable_and_authoritative(live_catalog):
    assert live_catalog.source == "live", f"live discovery fell back: {live_catalog.detail}"
    assert live_catalog.degraded is False
    assert live_catalog.models, "the live catalog returned no models"

    ids = [m.id for m in live_catalog.models]
    # Model ids keep their vendor/model namespace verbatim.
    assert any("/" in model_id for model_id in ids)
    assert len(ids) == len(set(ids)), "duplicate ids in the live catalog"


def test_live_text_dropdown_contains_only_chat_compatible_models(live_catalog):
    options = filter_models(live_catalog.models, CAPABILITY_CHAT)
    assert options, "no chat-capable models in the live catalog"

    for option in options:
        types = set(option.supported_endpoint_types)
        # Every offered model can actually serve a chat completion.
        assert types & {"openai", "anthropic", "gemini", "openai-response"}, option.id
        # No dedicated non-text route leaked into the text dropdown.
        assert not (types & {"image-generation", "openai-video", "jina-rerank", "embeddings"}), option.id

    print(f"\nlive chat models: {len(options)} / catalog {len(live_catalog.models)}")


def test_live_multimodal_filter_is_fail_closed(live_catalog):
    vision = filter_models(live_catalog.models, CAPABILITY_CHAT, "image")
    text_only = filter_models(live_catalog.models, CAPABILITY_CHAT)
    print(f"\nlive image-input chat models: {len(vision)}")

    for option in vision:
        # Every multimodal option explicitly declares image input.
        assert "image" in option.input_modalities, option.id
    # The multimodal list is a strict subset of the text list.
    assert {m.id for m in vision} <= {m.id for m in text_only}


def test_live_inference_through_the_provider_path(live_store):
    """One real request through the shipped provider code, not a bare curl."""
    origins = resolve_origins({})
    config = resolve_orcarouter_config(
        provider="orcarouter", model="", store=live_store, origins=origins
    )
    assert config.base_url == "https://api.orcarouter.ai/v1"
    assert config.api_key == LIVE_KEY
    assert config.credential.method == METHOD_API_KEY

    catalog: Catalog = ModelDiscovery(origins, api_key=LIVE_KEY).fetch()
    assert catalog.source == "live"
    chat_models = [m.id for m in filter_models(catalog.models, CAPABILITY_CHAT)]
    assert chat_models

    # Which models a given key may call is a per-key policy, so try the
    # workspace-preference route first and fall back through the live list
    # rather than assuming any single id is callable.
    preferred = ["orcarouter/auto", "deepseek/deepseek-v4-pro", "google/gemini-3.5-flash"]
    ordered = [m for m in preferred if m in chat_models] + [m for m in chat_models if m not in preferred]

    last_error: Exception | None = None
    for model in ordered[:6]:
        config.model = model
        client = build_orcarouter_client(config, live_store, origins)
        try:
            reply = client.chat([{"role": "user", "content": "Reply with the single word: ok"}])
        except Exception as exc:  # noqa: BLE001 - a key-scoped denial is not a wiring bug
            last_error = exc
            continue
        assert isinstance(reply, str) and reply.strip(), "the live request returned nothing"
        print(f"\nlive inference ok via model={model}")
        return

    raise AssertionError(f"no callable chat model for this key: {last_error}")
