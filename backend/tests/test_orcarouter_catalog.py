"""Model catalog and capability-filter tests.

The fixture catalog deliberately covers every shape the filters must handle:
a text-only chat model, an image-input chat model, an embedding model, an
image-generation model, a video model, and a rerank model. Models whose
metadata is missing or ambiguous must fail closed.
"""

from __future__ import annotations

import json

import pytest

from app.llm.orcarouter import (
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDING,
    CAPABILITY_IMAGE,
    CAPABILITY_RERANK,
    CAPABILITY_VIDEO,
    Catalog,
    ModelDiscovery,
    SEED_SOURCE,
    filter_models,
    is_compatible,
    parse_catalog,
    resolve_origins,
    seed_catalog,
    select_models,
)

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
            "context_length": 200000,
            "supported_endpoint_types": ["openai", "anthropic"],
            "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
        },
        {
            "id": "acme/audio-chat",
            "name": "Acme Audio Chat",
            "supported_endpoint_types": ["openai"],
            "architecture": {"input_modalities": ["text", "audio"], "output_modalities": ["text"]},
        },
        {
            "id": "acme/embed-small",
            "name": "Acme Embedding Small",
            "supported_endpoint_types": ["embeddings"],
            "architecture": {"input_modalities": ["text"], "output_modalities": ["embedding"]},
        },
        {
            "id": "acme/image-xl",
            "name": "Acme Image XL",
            "supported_endpoint_types": ["image-generation"],
            "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]},
        },
        {
            "id": "acme/video-1",
            "name": "Acme Video",
            "supported_endpoint_types": ["openai-video"],
            "architecture": {"input_modalities": ["text"], "output_modalities": ["video"]},
        },
        {
            "id": "acme/rerank-1",
            "name": "Acme Rerank",
            "supported_endpoint_types": ["jina-rerank"],
        },
        {
            "id": "acme/undeclared",
            "name": "Acme Undeclared Modalities",
            "supported_endpoint_types": ["openai"],
        },
    ]
}


@pytest.fixture()
def catalog():
    return Catalog(models=parse_catalog(FIXTURE), source="live", degraded=False)


def ids(records):
    return [r.id for r in records]


def test_parse_keeps_vendor_namespace_and_metadata():
    records = {r.id: r for r in parse_catalog(FIXTURE)}
    assert "acme/vision-chat" in records
    vision = records["acme/vision-chat"]
    assert vision.context_length == 200000
    assert vision.input_modalities == ["text", "image"]
    assert vision.supported_endpoint_types == ["openai", "anthropic"]
    # A live record never gets a guessed reasoning ladder.
    assert vision.reasoning_efforts == []
    assert vision.source == "live"


def test_parse_is_bounded_and_drops_junk_entries():
    payload = {
        "data": [
            {"id": "ok/model", "supported_endpoint_types": ["openai"]},
            {"id": ""},
            {"id": "x" * 500},
            {"id": "dup/model"},
            {"id": "dup/model"},
            "not-a-dict",
            {"no_id": True},
            {"id": "bad/ints", "context_length": -5, "max_completion_tokens": "many"},
        ]
    }
    records = {r.id: r for r in parse_catalog(payload)}
    assert set(records) == {"ok/model", "dup/model", "bad/ints"}
    assert records["bad/ints"].context_length is None
    assert records["bad/ints"].max_completion_tokens is None


def test_item_count_is_capped():
    payload = {"data": [{"id": f"m/{i}"} for i in range(1000)]}
    assert len(parse_catalog(payload)) <= 400


def test_malformed_payload_yields_nothing():
    for payload in ([], {}, None, {"data": "nope"}, {"data": None}):
        assert parse_catalog(payload) == []


def test_chat_filter_excludes_dedicated_non_text_routes(catalog):
    chat_ids = ids(filter_models(catalog.models, CAPABILITY_CHAT))
    assert "acme/text-only" in chat_ids
    assert "acme/vision-chat" in chat_ids
    for excluded in ("acme/embed-small", "acme/image-xl", "acme/video-1", "acme/rerank-1"):
        assert excluded not in chat_ids


def test_multimodal_filter_fails_closed(catalog):
    image_ids = ids(filter_models(catalog.models, CAPABILITY_CHAT, "image"))
    assert image_ids == ["acme/vision-chat"]
    # A chat model that never declared image input is not offered for an image.
    assert "acme/text-only" not in image_ids
    # Missing modality metadata fails closed rather than assuming support.
    assert "acme/undeclared" not in image_ids

    audio_ids = ids(filter_models(catalog.models, CAPABILITY_CHAT, "audio"))
    assert audio_ids == ["acme/audio-chat"]

    video_ids = ids(filter_models(catalog.models, CAPABILITY_CHAT, "video"))
    assert video_ids == []


def test_text_filter_is_unaffected_by_modality(catalog):
    text_ids = ids(filter_models(catalog.models, CAPABILITY_CHAT, "text"))
    assert "acme/text-only" in text_ids
    assert "acme/undeclared" in text_ids


@pytest.mark.parametrize(
    "capability,expected",
    [
        (CAPABILITY_EMBEDDING, ["acme/embed-small"]),
        (CAPABILITY_IMAGE, ["acme/image-xl"]),
        (CAPABILITY_VIDEO, ["acme/video-1"]),
        (CAPABILITY_RERANK, ["acme/rerank-1"]),
    ],
)
def test_specialised_capabilities_match_strictly(catalog, capability, expected):
    assert ids(filter_models(catalog.models, capability)) == expected


def test_unknown_capability_is_rejected(catalog):
    with pytest.raises(ValueError):
        filter_models(catalog.models, "telepathy")


def test_stale_selection_is_detected(catalog):
    assert is_compatible(catalog.models, "acme/text-only", CAPABILITY_CHAT)
    assert not is_compatible(catalog.models, "acme/image-xl", CAPABILITY_CHAT)
    # The same model id is valid for chat-with-image but not for text-only chat.
    assert is_compatible(catalog.models, "acme/vision-chat", CAPABILITY_CHAT, "image")
    assert not is_compatible(catalog.models, "acme/vision-chat", CAPABILITY_EMBEDDING)


def test_select_models_reports_provenance(catalog):
    payload = select_models(CAPABILITY_CHAT, None, catalog)
    assert payload["source"] == "live"
    assert payload["degraded"] is False
    assert payload["count"] == len(payload["options"])
    assert all("id" in option for option in payload["options"])


def test_seed_preserves_verified_metadata():
    seed = {r.id: r for r in seed_catalog()}
    gpt = seed["openai/gpt-5.5"]
    # The verified reasoning ladder must survive the seed definition.
    assert gpt.reasoning_efforts == ["low", "medium", "high", "xhigh"]
    assert gpt.context_length == 400000
    assert "image" in gpt.input_modalities
    assert gpt.source == SEED_SOURCE
    assert seed["deepseek/deepseek-v4-pro"].context_length == 1048576
    assert seed["orcarouter/auto"].id == "orcarouter/auto"
    assert set(seed) == {
        "openai/gpt-5.5",
        "anthropic/claude-opus-4.8",
        "google/gemini-3.5-flash",
        "deepseek/deepseek-v4-pro",
        "orcarouter/auto",
    }


def test_seed_is_chat_filterable_and_gpt55_keeps_its_ladder():
    payload = select_models(CAPABILITY_CHAT, None, Catalog(models=seed_catalog(), source="seed", degraded=True))
    by_id = {o["id"]: o for o in payload["options"]}
    assert by_id["openai/gpt-5.5"]["reasoning_efforts"] == ["low", "medium", "high", "xhigh"]
    assert by_id["orcarouter/auto"]["reasoning_efforts"] == []


def test_seed_contains_no_embedding_or_image_routes():
    payload = select_models(CAPABILITY_EMBEDDING, None, Catalog(models=seed_catalog(), source="seed", degraded=True))
    assert payload["options"] == []


class FakeResponse:
    def __init__(self, status_code, payload, raw=None):
        self.status_code = status_code
        self._payload = payload
        self.content = raw if raw is not None else json.dumps(payload).encode("utf-8")

    def json(self):
        return self._payload


class FakeTransport:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, headers=None):
        self.calls.append({"url": url, "headers": headers or {}})
        if self.error:
            raise self.error
        return self.response


def test_live_discovery_is_authoritative():
    transport = FakeTransport(response=FakeResponse(200, FIXTURE))
    discovery = ModelDiscovery(resolve_origins({}), api_key="sk-orca-fake", transport=transport)
    catalog = discovery.fetch()
    assert catalog.source == "live"
    assert catalog.degraded is False
    assert len(catalog.models) == len(FIXTURE["data"])
    assert transport.calls[0]["url"] == "https://api.orcarouter.ai/v1/models"
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer sk-orca-fake"


def test_discovery_does_not_proxy_loopback_and_uses_the_api_origin():
    transport = FakeTransport(response=FakeResponse(200, FIXTURE))
    discovery = ModelDiscovery(resolve_origins({}), transport=transport)
    discovery.fetch()
    url = transport.calls[0]["url"]
    assert url.startswith("https://api.orcarouter.ai/v1/models")
    # Never the auth origin, and never the auth path.
    assert "www.orcarouter.ai" not in url
    assert "/auth/keys" not in url


def test_discovery_falls_back_to_the_seed_and_never_merges():
    transport = FakeTransport(error=RuntimeError("boom"))
    discovery = ModelDiscovery(resolve_origins({}), transport=transport)
    # Force the transport error to look like an httpx failure.
    transport.error = __import__("httpx").ConnectError("boom")
    catalog = discovery.fetch()
    assert catalog.source == "seed"
    assert catalog.degraded is True
    assert catalog.detail
    assert {m.id for m in catalog.models} == {m.id for m in seed_catalog()}
    # The seed is the whole list: no live id is mixed in.
    assert all(m.source == SEED_SOURCE for m in catalog.models)


def test_discovery_uses_last_known_good_over_the_seed():
    good = FakeTransport(response=FakeResponse(200, FIXTURE))
    discovery = ModelDiscovery(resolve_origins({}), transport=good)
    live = discovery.fetch(now=1000.0)
    assert live.source == "live"

    discovery._transport = FakeTransport(error=__import__("httpx").ConnectError("boom"))
    cached = discovery.fetch(now=1010.0)
    assert cached.source == "cache"
    assert cached.degraded is True
    assert {m.id for m in cached.models} == {m.id for m in live.models}


def test_discovery_rejects_oversized_and_invalid_responses():
    import httpx

    too_big = FakeTransport(response=FakeResponse(200, {}, raw=b"x" * (600 * 1024)))
    assert ModelDiscovery(resolve_origins({}), transport=too_big).fetch().source == "seed"

    not_json = FakeTransport(response=FakeResponse(200, {}, raw=b"<html>"))
    assert ModelDiscovery(resolve_origins({}), transport=not_json).fetch().source == "seed"

    empty = FakeTransport(response=FakeResponse(200, {"data": []}))
    assert ModelDiscovery(resolve_origins({}), transport=empty).fetch().source == "seed"

    unauthorized = FakeTransport(response=FakeResponse(401, {"error": "nope"}))
    catalog = ModelDiscovery(resolve_origins({}), transport=unauthorized).fetch()
    assert catalog.source == "seed"
    assert "401" in catalog.detail


def test_discovery_falls_back_to_anonymous_when_the_key_cannot_list_models():
    """A key that is refused for the catalog listing must not blank the list."""

    class SequenceTransport:
        def __init__(self):
            self.calls = []

        def get(self, url, headers=None):
            headers = headers or {}
            self.calls.append(headers.get("Authorization", ""))
            if headers.get("Authorization"):
                return FakeResponse(401, {"error": "unauthorized"})
            return FakeResponse(200, FIXTURE)

    transport = SequenceTransport()
    catalog = ModelDiscovery(resolve_origins({}), api_key="sk-orca-fake", transport=transport).fetch()

    assert catalog.source == "live"
    assert catalog.degraded is False
    # Exactly two requests: one with the key, one anonymous.
    assert transport.calls == ["Bearer sk-orca-fake", ""]
    assert "匿名" in catalog.detail


def test_discovery_never_hides_a_total_catalog_failure():
    class AlwaysUnauthorized:
        def get(self, url, headers=None):
            return FakeResponse(401, {"error": "unauthorized"})

    catalog = ModelDiscovery(resolve_origins({}), api_key="sk-orca-fake", transport=AlwaysUnauthorized()).fetch()
    assert catalog.source == "seed"
    assert catalog.degraded is True


def test_seed_options_never_come_from_a_free_text_field(catalog):
    payload = select_models(CAPABILITY_CHAT, "image", catalog)
    assert payload["options"], "the vision model must be selectable for an image chat"
    assert all(option["id"] for option in payload["options"])
    assert all("/" in option["id"] for option in payload["options"])
