"""Bounded live model discovery for OrcaRouter.

Live discovery improves a provider entry; it never makes one unusable. The
request is bounded in time and bytes, and a failure falls back to the last
known-good catalog and then to the verified seed, with a degraded flag the UI
surfaces so nobody mistakes a stale list for a live one.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, List, Optional

import httpx

from .catalog import (
    CACHE_TTL_SECONDS,
    FETCH_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    Catalog,
    ModelRecord,
    parse_catalog,
    seed_catalog,
)
from .net import get_json
from .origins import Origins


class DiscoveryError(RuntimeError):
    """Live discovery failed. The caller falls back; the message is user-safe."""


@dataclass
class _CacheEntry:
    models: List[ModelRecord]
    fetched_at: float


class ModelDiscovery:
    """Fetches and caches the OrcaRouter catalog for one API origin."""

    def __init__(self, origins: Origins, api_key: str = "", transport: Any = None):
        self.origins = origins
        self.api_key = api_key
        self._transport = transport
        self._cache: Optional[_CacheEntry] = None
        self.last_note = ""

    # -- fetching ---------------------------------------------------------

    def fetch(self, *, now: Optional[float] = None) -> Catalog:
        """Fetch the live catalog, falling back to cache and then the seed."""
        now = time.time() if now is None else now
        try:
            models = self._fetch_live()
        except DiscoveryError as exc:
            return self._fallback(str(exc), now)
        self._cache = _CacheEntry(models=models, fetched_at=now)
        return Catalog(models=models, source="live", degraded=False, detail=self.last_note)

    def _fetch_live(self) -> List[ModelRecord]:
        models, note = self._request(self.api_key)
        self.last_note = note
        return models

    def _request(self, api_key: str) -> tuple[List[ModelRecord], str]:
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        url = self.origins.models_url
        try:
            response = get_json(
                url, timeout=FETCH_TIMEOUT_SECONDS, headers=headers, transport=self._transport
            )
        except httpx.HTTPError as exc:
            raise DiscoveryError(f"模型目录请求失败: {type(exc).__name__}") from exc

        if response.status_code == 401:
            if api_key:
                # The key was refused for the catalog listing. The catalog is
                # public, so try once without it rather than blanking the model
                # list; validity of the key is settled by the first real request.
                models, _ = self._request("")
                return models, "目录以匿名方式获取：当前 Key 未获授权列出模型"
            raise DiscoveryError("模型目录鉴权失败 (401)")
        if response.status_code >= 400:
            raise DiscoveryError(f"模型目录返回 HTTP {response.status_code}")

        raw = response.content
        if len(raw) > MAX_RESPONSE_BYTES:
            raise DiscoveryError("模型目录响应过大，已拒绝解析")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DiscoveryError("模型目录响应不是合法 JSON") from exc

        models = parse_catalog(payload, source="live")
        if not models:
            raise DiscoveryError("模型目录未返回任何可用模型")
        return models, ""

    def _fallback(self, detail: str, now: float) -> Catalog:
        cached = self._cache
        if cached is not None and (now - cached.fetched_at) <= CACHE_TTL_SECONDS * 12:
            return Catalog(
                models=list(cached.models),
                source="cache",
                degraded=True,
                detail=f"{detail}（使用最近一次成功获取的目录）",
            )
        return Catalog(
            models=seed_catalog(),
            source="seed",
            degraded=True,
            detail=f"{detail}（使用已验证的内置模型列表）",
        )
