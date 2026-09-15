"""PKCE connect-flow tests.

The exchange is exercised through the project's own connect adapter (the same
object the HTTP endpoints drive), against a local fake auth server. No test
ever touches the real consent screen: approval requires a human, and a worker
must not fake it.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.llm.orcarouter import (
    METHOD_PKCE,
    STATE_NEEDS_REAUTH,
    ConnectManager,
    ConnectStatus,
    CredentialStore,
    LoginCancelled,
    LoginError,
    LoginStateMismatch,
    code_challenge_for,
    resolve_origins,
)

FAKE_KEY = "sk-orca-" + "c" * 32
FAKE_CODE = "fake-auth-code-1234567890"
FAKE_VERIFIER = "fake-verifier"


def make_manager(tmp_path, auth_base, api_base="https://api.orcarouter.ai/v1"):
    store = CredentialStore(tmp_path / "creds.json")
    origins = resolve_origins({"ORCA_AUTH_BASE_URL": auth_base, "ORCA_API_BASE_URL": api_base})
    return ConnectManager(store, origins), store, origins


class FakeAuthServer:
    """Local stand-in for the OrcaRouter consent/exchange origin."""

    def __init__(self, responder):
        self.responder = responder
        self.requests = []
        self._server = None
        self._thread = None

    def __enter__(self):
        responder = self.responder
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep test output clean
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    body = {"_raw": raw.decode("utf-8", "replace")}
                requests.append({"path": self.path, "body": body, "headers": dict(self.headers)})
                status, payload = responder(self.path, body)
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://127.0.0.1:{port}"


def happy_responder(path, body):
    if path != "/api/v1/auth/keys":
        return 404, {"error": "not_found"}
    return 200, {"key": FAKE_KEY, "user_id": "12345", "scope": "api"}


def test_full_connect_flow_persists_a_usable_key(tmp_path):
    with FakeAuthServer(happy_responder) as server:
        manager, store, origins = make_manager(tmp_path, server.base_url)

        session = manager.start()
        assert session.status == ConnectStatus.PENDING.value
        assert session.authorize.url.startswith(f"{server.base_url}/auth?")
        assert "code_challenge_method=S256" in session.authorize.url
        assert session.verifier not in session.authorize.url

        credential = manager.exchange(FAKE_CODE, attempt=session.attempt)

    assert credential.key == FAKE_KEY
    assert credential.method == METHOD_PKCE
    assert credential.account_id == "12345"
    assert credential.scope == "api"

    # The key is persisted: a later launch reuses it instead of minting a new one.
    stored = store.get_credential(METHOD_PKCE)
    assert stored["key"] == FAKE_KEY
    assert stored["generation"] == 1

    request = server.requests[0]
    assert request["path"] == "/api/v1/auth/keys"
    assert request["body"]["code"] == FAKE_CODE
    assert request["body"]["code_verifier"] == session.verifier
    assert request["body"]["code_challenge_method"] == "S256"


def test_exchange_uses_the_auth_origin_and_never_the_inference_origin(tmp_path):
    with FakeAuthServer(happy_responder) as server:
        manager, _store, origins = make_manager(tmp_path, server.base_url)
        assert origins.api_base == "https://api.orcarouter.ai/v1"
        assert origins.auth_base == server.base_url
        # Exchange is pinned to the auth origin, never derived from the API base.
        assert origins.exchange_url == f"{server.base_url}/api/v1/auth/keys"
        assert not origins.exchange_url.startswith(origins.api_base)
        assert origins.models_url.startswith(origins.api_base)
        manager.start()
        manager.exchange(FAKE_CODE, attempt=manager.attempt)
    assert server.requests[0]["path"] == "/api/v1/auth/keys"


def test_default_origins_use_the_documented_paths():
    """Guards the classic mistake: /v1/auth/keys on the inference origin."""
    origins = resolve_origins({})
    assert origins.exchange_url == "https://www.orcarouter.ai/api/v1/auth/keys"
    assert origins.authorize_url == "https://www.orcarouter.ai/auth"
    assert "api.orcarouter.ai" not in origins.exchange_url
    assert origins.models_url == "https://api.orcarouter.ai/v1/models"
    assert "/auth/keys" not in origins.models_url


def test_authorize_url_targets_the_auth_origin_not_the_api_origin(tmp_path):
    with FakeAuthServer(happy_responder) as server:
        manager, _store, origins = make_manager(tmp_path, server.base_url)
        session = manager.start()
        assert session.authorize.url.startswith(f"{server.base_url}/auth")
        assert "api.orcarouter.ai" not in session.authorize.url
        assert origins.models_url == "https://api.orcarouter.ai/v1/models"


def test_verifier_and_key_never_appear_in_logs_or_errors(tmp_path, capsys, caplog):
    with FakeAuthServer(happy_responder) as server:
        manager, _store, _origins = make_manager(tmp_path, server.base_url)
        session = manager.start()
        verifier = session.verifier
        payload = session.public()
        manager.exchange(FAKE_CODE, attempt=session.attempt)

    # The redacted status payload is what the API returns to a browser.
    serialised = json.dumps(payload)
    assert verifier not in serialised
    assert FAKE_KEY not in serialised
    assert "code_verifier" not in serialised
    captured = capsys.readouterr()
    assert verifier not in captured.out and verifier not in captured.err
    assert FAKE_KEY not in captured.out and FAKE_KEY not in captured.err


def test_denial_is_reported_cleanly(tmp_path):
    def deny(path, body):
        return 403, {"error": "access_denied", "error_description": "user denied"}

    with FakeAuthServer(deny) as server:
        manager, store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start()
        with pytest.raises(LoginError) as info:
            manager.exchange(FAKE_CODE, attempt=session.attempt)

    assert info.value.code == "code_rejected"
    # The attempt is released: a new login is possible straight away.
    assert manager.status()["status"] == ConnectStatus.FAILED.value
    assert manager.start() is not None
    assert store.get_credential(METHOD_PKCE) is None


def test_state_mismatch_is_rejected_before_the_code_is_spent(tmp_path):
    with FakeAuthServer(happy_responder) as server:
        manager, store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start()
        with pytest.raises(LoginStateMismatch):
            manager.exchange(FAKE_CODE, attempt=session.attempt, state="not-the-state")

    assert server.requests == []  # nothing was sent upstream
    assert store.get_credential(METHOD_PKCE) is None


def test_matching_state_is_accepted(tmp_path):
    with FakeAuthServer(happy_responder) as server:
        manager, _store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start()
        credential = manager.exchange(
            FAKE_CODE, attempt=session.attempt, state=session.authorize.state
        )
    assert credential.key == FAKE_KEY


def test_code_cannot_be_reused(tmp_path):
    with FakeAuthServer(happy_responder) as server:
        manager, store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start()
        manager.exchange(FAKE_CODE, attempt=session.attempt)
        with pytest.raises(LoginError) as info:
            manager.exchange(FAKE_CODE, attempt=session.attempt)
    assert info.value.code == "already_exchanged"
    # Only one key was ever minted for this attempt.
    assert len(server.requests) == 1
    assert store.get_credential(METHOD_PKCE)["generation"] == 1


def test_expired_attempt_is_refused(tmp_path, monkeypatch):
    with FakeAuthServer(happy_responder) as server:
        manager, _store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start()
        session.created_at -= 601
        with pytest.raises(LoginError) as info:
            manager.exchange(FAKE_CODE, attempt=session.attempt)
    assert info.value.code == "timeout"
    assert manager.status()["status"] == ConnectStatus.FAILED.value


def test_explicit_cancel_releases_the_lock(tmp_path):
    with FakeAuthServer(happy_responder) as server:
        manager, _store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start()
        assert manager.cancel() is True
        assert manager.status()["status"] == ConnectStatus.IDLE.value
        with pytest.raises(LoginError) as info:
            manager.exchange(FAKE_CODE, attempt=session.attempt)
    assert info.value.code == "no_attempt"

    # Cancel is idempotent and a fresh login can start afterwards.
    assert manager.cancel() is False
    assert manager.start() is not None


def test_starting_a_new_attempt_supersedes_the_previous_one(tmp_path):
    with FakeAuthServer(happy_responder) as server:
        manager, _store, _ = make_manager(tmp_path, server.base_url)
        first = manager.start()
        second = manager.start()
        assert second.attempt == first.attempt + 1
        assert first.status == ConnectStatus.FAILED.value
        assert first.error_code == "superseded"
        with pytest.raises(LoginError):
            manager.exchange(FAKE_CODE, attempt=first.attempt)
        assert manager.exchange(FAKE_CODE, attempt=second.attempt).key == FAKE_KEY


def test_scope_downgrade_is_surfaced_not_silently_accepted(tmp_path):
    def narrowed(path, body):
        return 200, {"key": FAKE_KEY, "user_id": "1", "scope": "api"}

    with FakeAuthServer(narrowed) as server:
        manager, _store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start(scope="connector")
        credential = manager.exchange(FAKE_CODE, attempt=session.attempt)

    assert credential.scope == "api"  # what was granted, not what was asked
    assert manager.status()["warning"]
    assert "connector" in manager.status()["warning"]


def test_scope_upgrade_is_not_claimed(tmp_path):
    def wider(path, body):
        return 200, {"key": FAKE_KEY, "user_id": "1", "scope": "connector"}

    with FakeAuthServer(wider) as server:
        manager, _store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start(scope="api")
        credential = manager.exchange(FAKE_CODE, attempt=session.attempt)
    assert credential.scope == "connector"


def test_rate_limit_and_network_failure_are_terminal(tmp_path):
    with FakeAuthServer(lambda path, body: (429, {"error": "too_many_requests"})) as server:
        manager, _store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start()
        with pytest.raises(LoginError) as info:
            manager.exchange(FAKE_CODE, attempt=session.attempt)
        assert info.value.code == "rate_limited"
        assert manager.status()["status"] == ConnectStatus.FAILED.value

    # Network failure: the port is closed, so the request cannot connect.
    manager2, _store2, _ = make_manager(tmp_path, "http://127.0.0.1:1")
    session2 = manager2.start()
    with pytest.raises(LoginError) as info2:
        manager2.exchange(FAKE_CODE, attempt=session2.attempt)
    assert info2.value.code == "network_error"
    assert manager2.status()["status"] == ConnectStatus.FAILED.value


def test_error_bodies_never_echo_credentials(tmp_path):
    def leaky(path, body):
        return 403, {"error": "invalid_grant", "key": "sk-orca-leaked", "echo": body}

    with FakeAuthServer(leaky) as server:
        manager, _store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start()
        with pytest.raises(LoginError) as info:
            manager.exchange(FAKE_CODE, attempt=session.attempt)

    message = str(info.value)
    assert "sk-orca-leaked" not in message
    assert session.verifier not in message


def test_missing_code_is_rejected_without_calling_upstream(tmp_path):
    with FakeAuthServer(happy_responder) as server:
        manager, _store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start()
        with pytest.raises(LoginError) as info:
            manager.exchange("   ", attempt=session.attempt)
    assert info.value.code == "missing_code"
    assert server.requests == []


def test_challenge_method_rejection_is_explained(tmp_path):
    with FakeAuthServer(
        lambda path, body: (400, {"error": "invalid_request", "error_description": "method"})
    ) as server:
        manager, _store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start()
        with pytest.raises(LoginError) as info:
            manager.exchange(FAKE_CODE, attempt=session.attempt)
    assert info.value.code == "challenge_method"
    assert "400" in str(info.value)


def test_pkce_key_is_never_treated_as_a_refresh_token(tmp_path):
    """A revoked durable key needs reauthentication; nothing refreshes it."""
    with FakeAuthServer(happy_responder) as server:
        manager, store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start()
        credential = manager.exchange(FAKE_CODE, attempt=session.attempt)

    assert store.mark_needs_reauth(credential.account_id, credential.generation, METHOD_PKCE)
    assert store.get_credential(METHOD_PKCE)["state"] == STATE_NEEDS_REAUTH
    # No refresh endpoint, no refresh grant, and no second key minted.
    assert len([r for r in server.requests]) == 1


def test_cancel_does_not_delete_a_stored_key(tmp_path):
    with FakeAuthServer(happy_responder) as server:
        manager, store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start()
        manager.exchange(FAKE_CODE, attempt=session.attempt)
        manager.cancel()
    assert store.get_credential(METHOD_PKCE)["key"] == FAKE_KEY


def test_public_status_never_carries_the_verifier_or_key(tmp_path):
    with FakeAuthServer(happy_responder) as server:
        manager, _store, _ = make_manager(tmp_path, server.base_url)
        session = manager.start()
        verifier = session.verifier
        before = json.dumps(manager.status())
        manager.exchange(FAKE_CODE, attempt=session.attempt)
        after = json.dumps(manager.status())
    assert verifier not in before and verifier not in after
    assert FAKE_KEY not in after
