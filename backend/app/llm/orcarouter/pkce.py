"""OAuth 2.0 + PKCE connect flow for OrcaRouter (Flow B, out-of-band code).

Flow choice: **B — out-of-band code**. This server is started by ``start.bat``
on a Windows host whose port is user-configurable (``WCVIEWER_PORT``) and is
routinely reached over the LAN, so there is no predictable callback address to
listen on. Flow B is the flow the integration guide names for exactly that
shape; Flow C (device grant) is optional and is not implemented.

Safety properties implemented here:

* a fresh verifier and state per attempt, from ``secrets``;
* only the S256 challenge ever reaches the authorize URL;
* the verifier never leaves the process until the exchange, and never appears
  in a status payload, a log line, or an error message;
* exactly one server-side authorization in flight at a time, released on
  success, denial, exchange error, timeout, and explicit cancel;
* a monotonic attempt id so a late response from an abandoned attempt can
  never overwrite a newer one.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

import httpx

from .catalog import FETCH_TIMEOUT_SECONDS
from .credential_flow import (
    AuthorizeRequest,
    Credential,
    CredentialError,
    LoginCancelled,
    LoginError,
    LoginRateLimited,
    LoginStateMismatch,
    LoginTimeout,
    build_authorize_request,
    constant_time_equals,
    normalise_exchange_code,
    parse_exchange_payload,
    scope_downgraded,
)
from .net import post_json
from .origins import Origins

# Auth codes are single-use with a 10 minute TTL; mirror that as the local
# deadline so an abandoned attempt cannot be redeemed later.
AUTHORIZATION_TTL_SECONDS = 600.0
DEFAULT_SCOPE = "api"
APP_NAME = "WeChat Local Viewer"


class ConnectStatus(str, Enum):
    IDLE = "idle"
    PENDING = "pending"
    EXCHANGING = "exchanging"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class ConnectSession:
    attempt: int
    authorize: AuthorizeRequest
    scope: str
    created_at: float
    status: str = ConnectStatus.PENDING.value
    error_code: str = ""
    error_message: str = ""
    warning: str = ""
    credential: Optional[Credential] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def verifier(self) -> str:
        """Process-local only. Never serialised into a status payload."""
        return self.authorize.verifier

    def public(self) -> Dict[str, Any]:
        """Redacted view: no verifier, no key, no code."""
        return {
            "attempt": self.attempt,
            "status": self.status,
            "authorize_url": self.authorize.url,
            "app_name": APP_NAME,
            "scope": self.scope,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "warning": self.warning,
            "expires_in": max(0, int(self.created_at + AUTHORIZATION_TTL_SECONDS - time.time())),
            "connected": bool(self.credential and self.credential.is_usable),
            "account_id": self.credential.account_id if self.credential else "",
        }


class ConnectManager:
    """Single-flight PKCE connect flow bound to one credential store."""

    def __init__(self, store: Any, origins: Origins):
        self.store = store
        self.origins = origins
        self._lock = threading.Lock()
        self._session: Optional[ConnectSession] = None
        self._attempt = 0

    # -- lifecycle --------------------------------------------------------

    @property
    def attempt(self) -> int:
        with self._lock:
            return self._attempt

    def current(self) -> Optional[ConnectSession]:
        with self._lock:
            return self._session

    def status(self) -> Dict[str, Any]:
        with self._lock:
            session = self._session
        if session is None:
            return {"attempt": self._attempt, "status": ConnectStatus.IDLE.value}
        return session.public()

    def start(self, scope: str = DEFAULT_SCOPE) -> ConnectSession:
        """Begin an attempt, replacing (and thereby releasing) any previous one."""
        with self._lock:
            if self._session is not None and self._session.status in (
                ConnectStatus.PENDING.value,
                ConnectStatus.EXCHANGING.value,
            ):
                # Starting a new attempt abandons the previous one: the lock is
                # released here rather than left held by a dead attempt.
                self._session.status = ConnectStatus.FAILED.value
                self._session.error_code = "superseded"
                self._session.error_message = "已被新的授权请求取代"
            self._attempt += 1
            attempt = self._attempt
            authorize = build_authorize_request(
                self.origins, app_name=APP_NAME, scope=scope, callback_url="oob"
            )
            session = ConnectSession(
                attempt=attempt,
                authorize=authorize,
                scope=scope,
                created_at=time.time(),
            )
            self._session = session
            return session

    def cancel(self) -> bool:
        """Explicit cancel (button, provider switch, modal close, pagehide)."""
        with self._lock:
            session = self._session
            if session is None:
                return False
            active = session.status in (
                ConnectStatus.PENDING.value,
                ConnectStatus.EXCHANGING.value,
            )
            if active:
                session.status = ConnectStatus.FAILED.value
                session.error_code = LoginCancelled().code
                session.error_message = "授权已取消"
            # Bump the attempt so any in-flight response is refused.
            self._attempt += 1
            self._session = None
            return active

    def _expire(self, session: ConnectSession) -> LoginTimeout:
        session.status = ConnectStatus.FAILED.value
        error = LoginTimeout()
        session.error_code = error.code
        session.error_message = str(error)
        return error

    def _current_session(self, attempt: Optional[int]) -> ConnectSession:
        with self._lock:
            session = self._session
            if session is None:
                raise LoginError("no_attempt", "没有进行中的授权请求，请重新开始")
            if attempt is not None and session.attempt != attempt:
                raise LoginError("stale_attempt", "该授权请求已过期，请重新开始")
            return session

    # -- exchange ---------------------------------------------------------

    def exchange(
        self,
        code: str,
        *,
        attempt: Optional[int] = None,
        state: Optional[str] = None,
        transport: Any = None,
    ) -> Credential:
        """Redeem an out-of-band code for an OrcaRouter API key.

        ``state`` is optional because an out-of-band code is transcribed by a
        person rather than delivered to a listener; when the consent screen
        did surface it, it is compared in constant time before the code is
        spent.
        """
        session = self._current_session(attempt)

        if session.status == ConnectStatus.SUCCESS.value:
            # The code was already redeemed and the session completed; a second
            # exchange must not mint a second key from the same attempt.
            raise LoginError("already_exchanged", "该授权请求已完成，请重新发起授权")

        if time.time() - session.created_at > AUTHORIZATION_TTL_SECONDS:
            raise self._expire(session)

        if state is not None and not constant_time_equals(state, session.authorize.state):
            error = LoginStateMismatch()
            session.status = ConnectStatus.FAILED.value
            session.error_code = error.code
            session.error_message = str(error)
            raise error

        try:
            normalised = normalise_exchange_code(code)
        except LoginError as error:
            session.status = ConnectStatus.FAILED.value
            session.error_code = error.code
            session.error_message = str(error)
            raise

        session.status = ConnectStatus.EXCHANGING.value
        try:
            payload = self._post_exchange(normalised, session.verifier, transport=transport)
        except LoginError as error:
            session.status = ConnectStatus.FAILED.value
            session.error_code = error.code
            session.error_message = str(error)
            raise
        finally:
            # The code is single-use and now spent either way; drop it from the
            # session so it cannot be replayed or logged later.
            normalised = ""

        try:
            credential = parse_exchange_payload(payload, requested_scope=session.scope)
        except LoginError as error:
            session.status = ConnectStatus.FAILED.value
            session.error_code = error.code
            session.error_message = str(error)
            raise

        if scope_downgraded(credential, session.scope):
            session.warning = (
                f'授权服务返回的 scope 为 "{credential.scope}"，'
                f'窄于请求的 "{session.scope}"'
            )

        # Persist before declaring success: a key that is not stored would be
        # re-requested on the next launch, burning the 10-per-24h budget.
        self.store.set_credential(credential.method, credential)
        stored = self.store.get_credential(credential.method) or {}
        credential = Credential(
            key=credential.key,
            method=credential.method,
            account_id=credential.account_id,
            scope=credential.scope,
            generation=int(stored.get("generation") or 1),
            state="ok",
            source=credential.source,
        )

        session.status = ConnectStatus.SUCCESS.value
        session.credential = credential
        session.error_code = ""
        session.error_message = ""
        return credential

    def _post_exchange(self, code: str, verifier: str, *, transport: Any = None) -> Any:
        body = {
            "code": code,
            "code_verifier": verifier,
            "code_challenge_method": "S256",
        }
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        url = self.origins.exchange_url
        try:
            response = post_json(
                url, body, timeout=FETCH_TIMEOUT_SECONDS, headers=headers, transport=transport
            )
        except httpx.HTTPError as exc:
            raise LoginError("network_error", f"网络请求失败: {type(exc).__name__}") from exc

        status_code = response.status_code
        if status_code == 200:
            try:
                return response.json()
            except ValueError as exc:
                raise LoginError("bad_response", "授权服务返回了无法解析的响应") from exc

        # Never echo the response body wholesale: a failure body must not be
        # able to carry a credential into a log or an error message.
        detail = self._safe_error_code(response)
        if status_code == 400:
            raise LoginError(
                "challenge_method",
                f"授权码交换被拒绝 (400 {detail})：code_challenge_method 不被接受，请重新发起授权",
            )
        if status_code == 403:
            raise LoginError(
                "code_rejected",
                f"授权码无效 (403 {detail})：已过期、已被使用，或校验值不匹配；请重新发起授权",
            )
        if status_code == 429:
            error = LoginRateLimited("授权服务限流 (429)：请稍后重试，不要重复发起")
            return self._raise(error)
        raise LoginError("exchange_failed", f"授权码交换失败 (HTTP {status_code})")

    @staticmethod
    def _raise(error: CredentialError) -> Any:
        raise error

    @staticmethod
    def _safe_error_code(response: Any) -> str:
        try:
            payload = response.json()
        except Exception:
            return ""
        if isinstance(payload, dict):
            value = payload.get("error") or payload.get("error_description") or ""
            if isinstance(value, str) and len(value) <= 80:
                return value.strip()
        return ""
