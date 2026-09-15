"""Credential seam tests: both adapters must yield the same credential result."""

from __future__ import annotations

import json
import stat

import pytest

from app.llm.orcarouter import (
    METHOD_API_KEY,
    METHOD_PKCE,
    STATE_NEEDS_REAUTH,
    Credential,
    CredentialFormatError,
    CredentialMissingError,
    CredentialStore,
    build_authorize_request,
    code_challenge_for,
    get_credential_provider,
    mask_key,
    new_code_verifier,
    new_state,
    normalise_api_key,
    resolve_origins,
)

FAKE_KEY = "sk-orca-" + "a" * 32
FAKE_PKCE_KEY = "sk-orca-" + "b" * 32


@pytest.fixture()
def store(tmp_path):
    return CredentialStore(tmp_path / "orcarouter_credentials.json")


@pytest.fixture()
def origins():
    return resolve_origins({})


def test_api_key_adapter_saves_reads_and_masks(store, origins):
    provider = get_credential_provider(METHOD_API_KEY, store, origins)
    with pytest.raises(CredentialMissingError):
        provider.acquire()

    store.set_credential(
        METHOD_API_KEY, Credential(key=FAKE_KEY, method=METHOD_API_KEY, scope="api")
    )
    credential = provider.acquire()
    assert credential.key == FAKE_KEY
    assert credential.method == METHOD_API_KEY
    assert credential.is_usable

    # The raw key never appears in the redacted view.
    status = store.status()
    entry = next(e for e in status["methods"] if e["method"] == METHOD_API_KEY)
    assert entry["configured"] is True
    assert entry["secret_masked"] != FAKE_KEY
    assert FAKE_KEY not in json.dumps(status)
    assert entry["secret_masked"].startswith("sk-orca-")
    assert entry["secret_masked"].endswith(FAKE_KEY[-4:])


def test_both_adapters_produce_the_same_credential_shape(store, origins):
    store.set_credential(
        METHOD_API_KEY, Credential(key=FAKE_KEY, method=METHOD_API_KEY, scope="api")
    )
    store.set_credential(
        METHOD_PKCE,
        Credential(key=FAKE_PKCE_KEY, method=METHOD_PKCE, account_id="42", scope="api"),
    )

    from_api = get_credential_provider(METHOD_API_KEY, store, origins).acquire()
    from_pkce = get_credential_provider(METHOD_PKCE, store, origins).acquire()

    # Downstream code only sees Credential with a key, so it cannot branch on
    # which adapter produced it.
    for credential in (from_api, from_pkce):
        assert isinstance(credential, Credential)
        assert credential.is_usable
        assert credential.key.startswith("sk-orca-")
    assert from_api.method != from_pkce.method
    assert from_api.account_id == ""
    assert from_pkce.account_id == "42"


def test_key_can_be_updated_and_cleared(store, origins):
    store.set_credential(
        METHOD_API_KEY, Credential(key=FAKE_KEY, method=METHOD_API_KEY, scope="api")
    )
    store.set_credential(
        METHOD_API_KEY,
        Credential(key=FAKE_PKCE_KEY, method=METHOD_API_KEY, scope="api"),
    )
    assert get_credential_provider(METHOD_API_KEY, store, origins).acquire().key == FAKE_PKCE_KEY

    store.clear(METHOD_API_KEY)
    with pytest.raises(CredentialMissingError):
        get_credential_provider(METHOD_API_KEY, store, origins).acquire()
    assert store.status()["methods"][0]["configured"] is False


def test_clearing_one_method_keeps_the_other(store, origins):
    store.set_credential(
        METHOD_API_KEY, Credential(key=FAKE_KEY, method=METHOD_API_KEY, scope="api")
    )
    store.set_credential(
        METHOD_PKCE, Credential(key=FAKE_PKCE_KEY, method=METHOD_PKCE, scope="api")
    )
    store.clear(METHOD_API_KEY)
    assert get_credential_provider(METHOD_PKCE, store, origins).acquire().key == FAKE_PKCE_KEY


def test_key_format_checks_reject_obvious_mistakes():
    assert normalise_api_key("  " + FAKE_KEY + "  ") == FAKE_KEY
    assert normalise_api_key(f'"{FAKE_KEY}"') == FAKE_KEY
    with pytest.raises(CredentialFormatError):
        normalise_api_key("")
    with pytest.raises(CredentialFormatError):
        normalise_api_key("sk-orca-with space")
    with pytest.raises(CredentialFormatError):
        normalise_api_key("not-a-key")


def test_masking_never_leaks_the_middle_of_a_key():
    assert mask_key("") == ""
    assert mask_key("sk-orca-short") == "sk-orca-…"
    masked = mask_key(FAKE_KEY)
    assert FAKE_KEY not in masked
    assert FAKE_KEY[12:-4] not in masked


def test_store_file_is_owner_only_and_survives_reload(tmp_path):
    path = tmp_path / "creds.json"
    store = CredentialStore(path)
    store.set_credential(
        METHOD_API_KEY, Credential(key=FAKE_KEY, method=METHOD_API_KEY, scope="api")
    )
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    # A fresh instance reads the same value: the key survives a restart.
    assert CredentialStore(path).get_credential(METHOD_API_KEY)["key"] == FAKE_KEY


def test_corrupt_store_is_treated_as_unconfigured_not_a_crash(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text("{not json", encoding="utf-8")
    store = CredentialStore(path)
    assert store.get_credential(METHOD_API_KEY) is None
    assert store.status()["methods"][0]["configured"] is False


def test_active_method_prefers_an_actually_configured_method(store):
    store.set_active_method(METHOD_PKCE)
    # The explicit choice stands while nothing else is configured.
    assert store.resolve_active_method() == METHOD_PKCE
    store.set_credential(
        METHOD_API_KEY, Credential(key=FAKE_KEY, method=METHOD_API_KEY, scope="api")
    )
    # Storing a key makes that method active: the last credential configured wins
    # over a stale preference pointing at a method with no key.
    assert store.resolve_active_method() == METHOD_API_KEY
    # An explicit switch back is honoured once that method has a key.
    store.set_credential(
        METHOD_PKCE, Credential(key=FAKE_PKCE_KEY, method=METHOD_PKCE, scope="api")
    )
    assert store.resolve_active_method() == METHOD_PKCE


def test_mark_needs_reauth_targets_one_generation(store):
    store.set_credential(
        METHOD_PKCE,
        Credential(key=FAKE_PKCE_KEY, method=METHOD_PKCE, account_id="7", scope="api"),
    )
    first = store.get_credential(METHOD_PKCE)
    assert store.mark_needs_reauth("7", first["generation"], METHOD_PKCE) is True
    entry = store.get_credential(METHOD_PKCE)
    assert entry["state"] == STATE_NEEDS_REAUTH
    # The secret is kept: a misclassified failure must not destroy the key.
    assert entry["key"] == FAKE_PKCE_KEY

    # Reconnect: a new generation is stored.
    store.set_credential(
        METHOD_PKCE,
        Credential(key=FAKE_KEY, method=METHOD_PKCE, account_id="7", scope="api"),
    )
    # A late 401 from the *old* generation must not mark the new credential.
    assert store.mark_needs_reauth("7", first["generation"], METHOD_PKCE) is False
    assert store.get_credential(METHOD_PKCE)["state"] == "ok"


def test_mark_needs_reauth_ignores_a_different_account(store):
    store.set_credential(
        METHOD_PKCE,
        Credential(key=FAKE_PKCE_KEY, method=METHOD_PKCE, account_id="7", scope="api"),
    )
    generation = store.get_credential(METHOD_PKCE)["generation"]
    assert store.mark_needs_reauth("999", generation, METHOD_PKCE) is False
    assert store.get_credential(METHOD_PKCE)["state"] == "ok"


def test_verifier_and_state_are_fresh_crypto_randomness():
    verifiers = {new_code_verifier() for _ in range(64)}
    states = {new_state() for _ in range(64)}
    assert len(verifiers) == 64
    assert len(states) == 64
    for verifier in verifiers:
        assert 40 <= len(verifier) <= 64
        assert "=" not in verifier
        assert "+" not in verifier and "/" not in verifier


def test_challenge_is_unpadded_base64url_sha256():
    import base64
    import hashlib

    verifier = "fixed-verifier-for-hash-shape-only"
    challenge = code_challenge_for(verifier)
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    assert challenge == expected
    assert "=" not in challenge


def test_authorize_url_carries_only_the_challenge(origins):
    request = build_authorize_request(origins, app_name="WeChat Local Viewer")
    assert request.url.startswith("https://www.orcarouter.ai/auth?")
    assert "code_challenge_method=S256" in request.url
    assert "callback_url=oob" in request.url
    assert request.challenge in request.url
    # The verifier must never ride on a URL.
    assert request.verifier not in request.url
    assert request.state in request.url
    assert request.challenge == code_challenge_for(request.verifier)


# --- outbound HTTP client: proxy handling -----------------------------------
#
# The host may advertise a proxy the process cannot actually use. httpx builds
# SOCKS transports without its optional `socksio` dependency and raises
# ImportError — sometimes when the client is constructed, sometimes on the first
# request — so `build_http_client` has to decide up front whether the advertised
# proxies are usable, or every OrcaRouter call dies on a host whose proxy was
# only ever meant for Git. `_proxies_are_usable` is that decision, and these
# tests pin it without ever opening a socket.
#
# Note what these tests can and cannot fake: patching `find_spec` changes the
# decision, but it does not install socksio, so whether httpx can then *build* a
# SOCKS transport still depends on the real environment. The assertions below
# therefore check the decision itself, and check the constructed client only
# where the proxy needs no optional dependency.


def _clear_proxy_environment(monkeypatch):
    """Drop every spelling of the proxy variables so a test's own proxy is the only one."""
    for name in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


def _no_socksio(monkeypatch, net):
    monkeypatch.setattr(
        net.importlib.util, "find_spec", lambda name: None if name == "socksio" else object()
    )


def test_socks_proxy_without_its_transport_is_rejected(monkeypatch):
    from app.llm.orcarouter import net

    _no_socksio(monkeypatch, net)
    _clear_proxy_environment(monkeypatch)
    for name in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        monkeypatch.setenv(name, "socks5://127.0.0.1:1080")
        monkeypatch.setenv(name.lower(), "socks5://127.0.0.1:1080")

    assert net._proxies_are_usable() is False
    with net.build_http_client(timeout=1.0) as client:
        assert client._trust_env is False


def test_socks_proxy_is_accepted_when_its_transport_is_available(monkeypatch):
    """The decision itself, both spellings, and every SOCKS variant httpx knows."""
    from app.llm.orcarouter import net

    monkeypatch.setattr(net.importlib.util, "find_spec", lambda name: object())
    for scheme in ("socks4", "socks4a", "socks5", "socks5h"):
        _clear_proxy_environment(monkeypatch)
        monkeypatch.setenv("HTTPS_PROXY", f"{scheme}://127.0.0.1:1080")
        assert net._proxies_are_usable() is True, scheme
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        monkeypatch.setenv("https_proxy", f"{scheme}://127.0.0.1:1080")
        assert net._proxies_are_usable() is True, scheme + " (lowercase)"


def test_the_client_still_ignores_an_unusable_proxy_even_for_a_working_scheme(monkeypatch):
    """One unusable proxy among several is enough to go direct."""
    from app.llm.orcarouter import net

    _no_socksio(monkeypatch, net)
    _clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    monkeypatch.setenv("HTTP_PROXY", "socks5://127.0.0.1:1080")

    assert net._proxies_are_usable() is False


def test_http_proxies_need_no_extra_dependency(monkeypatch):
    from app.llm.orcarouter import net

    _no_socksio(monkeypatch, net)
    _clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")

    assert net._proxies_are_usable() is True
    with net.build_http_client(timeout=1.0) as client:
        assert client._trust_env is True


def test_loopback_stays_direct_even_when_a_proxy_is_in_use(monkeypatch):
    """A proxied host must never route a credential exchange through that proxy."""
    from app.llm.orcarouter import net

    _clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")

    with net.build_http_client(timeout=1.0) as client:
        import httpx

        for host in (
            "http://127.0.0.1:8080/v1/models",
            "http://localhost:8080/v1/models",
            "http://[::1]:8080/v1/models",
        ):
            transport = client._transport_for_url(httpx.URL(host))
            # The mount registered ahead of the environment proxy map, not a
            # proxy transport that would carry the credential off-host.
            assert any(
                transport is mount for mount in net._LOOPBACK_MOUNTS.values()
            ), host
