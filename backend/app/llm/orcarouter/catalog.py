"""OrcaRouter model discovery and capability filtering.

The single source of truth for the model list is ``GET {api_base}/models`` on
the configured inference origin. When discovery succeeds it is authoritative;
the small seed below only keeps a fresh installation usable during an outage
or before the first key is entered.

Nothing here guesses a capability from a model's name. A model is offered for
an entry point only when the catalog's own metadata proves compatibility
(``supported_endpoint_types`` / ``architecture.input_modalities``), and a model
whose metadata is absent fails closed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Endpoint types that can serve a chat/completion request.
TEXT_ENDPOINT_TYPES = ("openai", "anthropic", "gemini", "openai-response")
# Endpoint types that are by definition *not* a general text chat route.
NON_TEXT_ENDPOINT_TYPES = ("image-generation", "openai-video", "jina-rerank", "embeddings")

# Entry-point capability ids used by the API and the UI.
CAPABILITY_CHAT = "chat"
CAPABILITY_EMBEDDING = "embedding"
CAPABILITY_IMAGE = "image"
CAPABILITY_VIDEO = "video"
CAPABILITY_RERANK = "rerank"
CAPABILITIES = (
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDING,
    CAPABILITY_IMAGE,
    CAPABILITY_VIDEO,
    CAPABILITY_RERANK,
)

# Bounds. A catalog response must not be able to consume unbounded memory, and
# the client must not advertise routes it cannot speak.
FETCH_TIMEOUT_SECONDS = 8.0
MAX_RESPONSE_BYTES = 512 * 1024
MAX_ITEMS = 400
MAX_ID_LENGTH = 200
CACHE_TTL_SECONDS = 300.0

# Verified cold-start seed. Sources: the OrcaRouter provider catalog, verified
# 2026-09-15 against GET https://api.orcarouter.ai/v1/models and the published
# model pages. These ids are the only hardcoded OrcaRouter model ids in the
# codebase; they exist so a fresh install is usable while the catalog is
# unreachable, and they are dropped the moment live discovery answers.
SEED_SOURCE = "verified-seed"
VERIFIED_SEED: Tuple[Dict[str, Any], ...] = (
    {
        "id": "openai/gpt-5.5",
        "name": "OpenAI: GPT-5.5",
        "context_length": 400_000,
        "max_completion_tokens": 128_000,
        "input_modalities": ["text", "image"],
        "supported_endpoint_types": ["openai", "openai-response", "anthropic"],
        # Verified reasoning-effort ladder; must survive live discovery.
        "reasoning_efforts": ["low", "medium", "high", "xhigh"],
    },
    {
        "id": "anthropic/claude-opus-4.8",
        "name": "Anthropic: Claude Opus 4.8",
        "context_length": 200_000,
        "max_completion_tokens": 64_000,
        "input_modalities": ["text", "image"],
        "supported_endpoint_types": ["anthropic", "openai", "openai-response"],
        "reasoning_efforts": ["low", "medium", "high"],
    },
    {
        "id": "google/gemini-3.5-flash",
        "name": "Google: Gemini 3.5 Flash",
        "context_length": 1_000_000,
        "max_completion_tokens": 65_536,
        "input_modalities": ["text", "image", "audio", "video"],
        "supported_endpoint_types": ["gemini", "openai", "openai-response"],
        "reasoning_efforts": ["low", "medium", "high"],
    },
    {
        "id": "deepseek/deepseek-v4-pro",
        "name": "DeepSeek: DeepSeek V4 Pro",
        "context_length": 1_048_576,
        "max_completion_tokens": 384_000,
        "input_modalities": ["text"],
        "supported_endpoint_types": ["openai", "openai-response", "anthropic"],
        "reasoning_efforts": ["low", "high", "max"],
    },
    {
        "id": "orcarouter/auto",
        "name": "OrcaRouter: Auto",
        "context_length": 1_000_000,
        "max_completion_tokens": 128_000,
        "input_modalities": ["text"],
        "supported_endpoint_types": ["openai", "openai-response", "anthropic", "gemini"],
        "reasoning_efforts": [],
    },
)

_SEED_BY_ID = {entry["id"]: entry for entry in VERIFIED_SEED}

# Reasoning metadata is only ever taken from the verified table above. The live
# catalog carries no reasoning field, so a live model never gets a guessed
# ladder; it inherits one only when its id is in the verified table.
VERIFIED_REASONING: Dict[str, List[str]] = {
    entry["id"]: list(entry["reasoning_efforts"]) for entry in VERIFIED_SEED
}


@dataclass
class ModelRecord:
    id: str
    name: str = ""
    context_length: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    input_modalities: List[str] = field(default_factory=list)
    supported_endpoint_types: List[str] = field(default_factory=list)
    reasoning_efforts: List[str] = field(default_factory=list)
    source: str = "live"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def chat_compatible(self) -> bool:
        types = set(self.supported_endpoint_types)
        if types & set(NON_TEXT_ENDPOINT_TYPES):
            return False
        return bool(types & set(TEXT_ENDPOINT_TYPES))

    def supports_input_modality(self, modality: str) -> bool:
        # Fail closed: a model that does not *declare* the modality is not
        # offered for it, even if its name suggests otherwise.
        if not self.input_modalities:
            return False
        return modality in self.input_modalities


def _coerce_str_list(value: Any, *, max_items: int = 16, max_len: int = 64) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value[:max_items]:
        if isinstance(item, str) and item and len(item) <= max_len:
            out.append(item)
    return out


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def parse_catalog(payload: Any, *, source: str = "live") -> List[ModelRecord]:
    """Turn a ``/v1/models`` body into bounded records, dropping junk entries."""
    if isinstance(payload, dict):
        items = payload.get("data")
    else:
        items = payload
    if not isinstance(items, list):
        return []

    records: List[ModelRecord] = []
    seen = set()
    for item in items:
        if len(records) >= MAX_ITEMS:
            break
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str):
            continue
        model_id = model_id.strip()
        if not model_id or len(model_id) > MAX_ID_LENGTH or model_id in seen:
            continue
        seen.add(model_id)

        architecture = item.get("architecture")
        modalities = _coerce_str_list(
            architecture.get("input_modalities") if isinstance(architecture, dict) else None
        )
        name = item.get("name")
        records.append(
            ModelRecord(
                id=model_id,
                name=name if isinstance(name, str) and len(name) <= 200 else "",
                context_length=_coerce_int(item.get("context_length")),
                max_completion_tokens=_coerce_int(item.get("max_completion_tokens")),
                input_modalities=modalities,
                supported_endpoint_types=_coerce_str_list(item.get("supported_endpoint_types")),
                reasoning_efforts=list(VERIFIED_REASONING.get(model_id, [])),
                source=source,
            )
        )
    return records


def seed_catalog() -> List[ModelRecord]:
    """The verified cold-start catalog. Never merged into a live result."""
    out: List[ModelRecord] = []
    for entry in VERIFIED_SEED:
        out.append(
            ModelRecord(
                id=entry["id"],
                name=entry["name"],
                context_length=entry["context_length"],
                max_completion_tokens=entry["max_completion_tokens"],
                input_modalities=list(entry["input_modalities"]),
                supported_endpoint_types=list(entry["supported_endpoint_types"]),
                reasoning_efforts=list(entry["reasoning_efforts"]),
                source=SEED_SOURCE,
            )
        )
    return out


def filter_models(
    records: Sequence[ModelRecord],
    capability: str,
    modality: Optional[str] = None,
) -> List[ModelRecord]:
    """Apply one entry point's capability rule to a catalog.

    * ``chat``      — text-capable and not a dedicated non-text route;
                      with ``modality`` set, additionally requires that the
                      model declares the uploaded input modality.
    * ``embedding`` — strictly the ``embeddings`` endpoint.
    * ``image``     — strictly ``image-generation``.
    * ``video``     — strictly ``openai-video``.
    * ``rerank``    — strictly ``jina-rerank``.
    """
    if capability == CAPABILITY_CHAT:
        out = [r for r in records if r.chat_compatible]
        if modality and modality != "text":
            out = [r for r in out if r.supports_input_modality(modality)]
        return out
    if capability == CAPABILITY_EMBEDDING:
        return [r for r in records if "embeddings" in r.supported_endpoint_types]
    if capability == CAPABILITY_IMAGE:
        return [r for r in records if "image-generation" in r.supported_endpoint_types]
    if capability == CAPABILITY_VIDEO:
        return [r for r in records if "openai-video" in r.supported_endpoint_types]
    if capability == CAPABILITY_RERANK:
        return [r for r in records if "jina-rerank" in r.supported_endpoint_types]
    raise ValueError(f"未知的能力: {capability}")


def is_compatible(records: Sequence[ModelRecord], model_id: str, capability: str, modality: Optional[str] = None) -> bool:
    """Whether a previously selected model id is still valid for an entry point."""
    return any(r.id == model_id for r in filter_models(records, capability, modality))


@dataclass
class Catalog:
    """A resolved catalog plus where it came from."""

    models: List[ModelRecord]
    source: str  # "live" | "cache" | "seed"
    degraded: bool
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "degraded": self.degraded,
            "detail": self.detail,
            "count": len(self.models),
            "models": [m.to_dict() for m in self.models],
        }


def select_models(
    capability: str,
    modality: Optional[str] = None,
    catalog: Optional[Catalog] = None,
) -> Dict[str, Any]:
    """The options a model selector should receive for one entry point."""
    catalog = catalog or Catalog(models=seed_catalog(), source="seed", degraded=True, detail="未获取目录")
    options = filter_models(catalog.models, capability, modality)
    return {
        "capability": capability,
        "modality": modality,
        "source": catalog.source,
        "degraded": catalog.degraded,
        "detail": catalog.detail,
        "count": len(options),
        "options": [m.to_dict() for m in options],
    }
