"""HTTP client construction for OrcaRouter calls.

Two things this module is careful about:

* **Loopback is never proxied.** A proxy configured for Git or another provider
  must not be able to intercept a credential exchange. Loopback mounts are
  registered as direct transports ahead of any environment proxy map.
* **A proxy the host cannot actually use does not break the feature.** If the
  environment advertises a proxy whose transport cannot be built (a SOCKS proxy
  without its optional dependency, for instance), the client falls back to a
  direct connection rather than failing at construction time.

The project itself never mutates proxy environment variables; it follows
whatever the host already configured.
"""

from __future__ import annotations

import importlib.util
import os
import urllib.parse
from typing import List, Optional

import httpx

_LOOPBACK_MOUNTS = {
    "http://127.0.0.1": httpx.HTTPTransport(retries=0),
    "http://localhost": httpx.HTTPTransport(retries=0),
    "http://[::1]": httpx.HTTPTransport(retries=0),
}

# Schemes httpx can only speak through its optional ``socksio`` dependency.
_SOCKS_SCHEMES = ("socks4", "socks4a", "socks5", "socks5h")


def _environment_proxy_urls() -> List[str]:
    """Proxy URLs the host advertises, both spellings, de-duplicated."""
    urls: List[str] = []
    for name in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        for key in (name, name.lower()):
            value = os.environ.get(key)
            if value and value not in urls:
                urls.append(value)
    return urls


def _proxies_are_usable() -> bool:
    """Whether every advertised proxy has the transport httpx needs to use it.

    httpx builds proxy transports lazily, so an unusable proxy — a SOCKS proxy
    without ``socksio``, the common case on a host that only configured one for
    Git — raises ImportError on the *first request* instead of when the client is
    constructed. That is why the direct fallback in :func:`build_http_client`
    could never fire. Checking the scheme up front makes it reachable.
    """
    for url in _environment_proxy_urls():
        scheme = urllib.parse.urlsplit(url).scheme.lower()
        if scheme in _SOCKS_SCHEMES and importlib.util.find_spec("socksio") is None:
            return False
    return True


def build_http_client(timeout: float) -> httpx.Client:
    if _proxies_are_usable():
        try:
            return httpx.Client(
                timeout=timeout,
                follow_redirects=False,
                mounts=dict(_LOOPBACK_MOUNTS),
            )
        except Exception:  # pragma: no cover - depends on the host's proxy config
            pass
    return httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False)


def post_json(
    url: str,
    body: dict,
    *,
    timeout: float,
    headers: Optional[dict] = None,
    transport: object = None,
) -> httpx.Response:
    """POST JSON, optionally through an injected transport (used by tests)."""
    if transport is not None:
        return transport.post(url, json=body, headers=headers or {})
    with build_http_client(timeout) as client:
        return client.post(url, json=body, headers=headers or {})


def get_json(
    url: str,
    *,
    timeout: float,
    headers: Optional[dict] = None,
    transport: object = None,
) -> httpx.Response:
    if transport is not None:
        return transport.get(url, headers=headers or {})
    with build_http_client(timeout) as client:
        return client.get(url, headers=headers or {})
