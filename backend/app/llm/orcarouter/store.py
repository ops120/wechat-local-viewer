"""Durable store for OrcaRouter credentials.

OrcaRouter issues a long-lived API key. There is no refresh grant, so the key
is written once and reused until OrcaRouter revokes it — a client that
re-authorizes on every launch would exhaust the 10-keys-per-user-per-24h cap.

OrcaRouter uses the project's existing secret location (the local ``.cache``
state directory, next to ``app.db``), not a new keyring. The file is created
with owner-only permissions, and every read path returns redacted metadata for
anything that leaves the process.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .credential_flow import (
    METHOD_API_KEY,
    METHOD_PKCE,
    STATE_OK,
    Credential,
    mask_key,
)

STORE_VERSION = 1
KNOWN_METHODS = (METHOD_API_KEY, METHOD_PKCE)


class CredentialStoreError(RuntimeError):
    pass


class CredentialStore:
    """JSON-backed credential store for the two OrcaRouter methods."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    # -- raw IO -----------------------------------------------------------

    def _load(self) -> Dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"version": STORE_VERSION, "methods": {}, "active_method": ""}
        except OSError as exc:  # unreadable file: behave as unconfigured, never crash
            raise CredentialStoreError(f"无法读取凭据文件: {exc.strerror or exc}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # A corrupt store is a terminal condition for the credential, not a
            # crash: report it as unconfigured so the user can re-enter a key.
            return {"version": STORE_VERSION, "methods": {}, "active_method": ""}
        if not isinstance(data, dict):
            return {"version": STORE_VERSION, "methods": {}, "active_method": ""}
        methods = data.get("methods")
        if not isinstance(methods, dict):
            methods = {}
        return {
            "version": STORE_VERSION,
            "methods": {k: v for k, v in methods.items() if isinstance(v, dict)},
            "active_method": data.get("active_method") or "",
        }

    def _save(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".orca-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # -- read -------------------------------------------------------------

    def get_credential(self, method: str) -> Optional[Dict[str, Any]]:
        entry = self._load()["methods"].get(method)
        if not entry or not entry.get("key"):
            return None
        return dict(entry)

    def resolve_active_method(self, configured_only: bool = True) -> str:
        """Pick the method to use when a request does not name one.

        The user's explicit choice wins while it still holds a key; otherwise
        fall back to whichever method actually has a credential.
        """
        data = self._load()
        active = data.get("active_method") or ""
        methods = data["methods"]
        if active in KNOWN_METHODS and (not configured_only or methods.get(active, {}).get("key")):
            return active
        for method in KNOWN_METHODS:
            if methods.get(method, {}).get("key"):
                return method
        return active if active in KNOWN_METHODS else METHOD_API_KEY

    # -- write ------------------------------------------------------------

    def set_credential(self, method: str, credential: Credential) -> None:
        if method not in KNOWN_METHODS:
            raise CredentialStoreError(f"未知的认证方式: {method}")
        data = self._load()
        previous = data["methods"].get(method) or {}
        generation = int(previous.get("generation") or 0) + 1
        data["methods"][method] = {
            "key": credential.key,
            "account_id": credential.account_id,
            "scope": credential.scope,
            "state": STATE_OK,
            "generation": generation,
            "updated_at": int(time.time()),
        }
        data["active_method"] = method
        self._save(data)

    def set_active_method(self, method: str) -> None:
        if method not in KNOWN_METHODS:
            raise CredentialStoreError(f"未知的认证方式: {method}")
        data = self._load()
        data["active_method"] = method
        self._save(data)

    def clear(self, method: str) -> None:
        if method not in KNOWN_METHODS:
            raise CredentialStoreError(f"未知的认证方式: {method}")
        data = self._load()
        data["methods"].pop(method, None)
        if data.get("active_method") == method:
            data["active_method"] = ""
        self._save(data)

    def mark_needs_reauth(self, account_id: str, generation: int, method: str) -> bool:
        """Terminal ``401`` handling for exactly one credential generation.

        Returns True when the entry was actually transitioned. A response that
        belongs to an older generation — a request that was already in flight
        when the user reconnected — updates nothing, so it cannot mark a fresh
        credential as broken.
        """
        if method not in KNOWN_METHODS:
            return False
        data = self._load()
        entry = data["methods"].get(method)
        if not entry or not entry.get("key"):
            return False
        if account_id and entry.get("account_id") and account_id != entry.get("account_id"):
            return False
        if int(entry.get("generation") or 0) != int(generation):
            return False
        if entry.get("state") == "needs_reauth":
            return False
        entry["state"] = "needs_reauth"
        # The secret itself is kept: a transient or misclassified failure must
        # not silently destroy a credential the user may still be able to use
        # after reconnecting.
        self._save(data)
        return True

    # -- redacted views ---------------------------------------------------

    def status(self, origins_auth_base: str = "") -> Dict[str, Any]:
        """Redacted snapshot safe for logs, API responses, and screenshots."""
        data = self._load()
        entries = []
        for method in KNOWN_METHODS:
            entry = data["methods"].get(method) or {}
            key = entry.get("key") or ""
            entries.append(
                {
                    "method": method,
                    "configured": bool(key),
                    "secret_masked": mask_key(key) if key else "",
                    "account_id": entry.get("account_id") or "",
                    "scope": entry.get("scope") or "",
                    "state": entry.get("state") or "unconfigured",
                    "generation": int(entry.get("generation") or 0),
                    "updated_at": int(entry.get("updated_at") or 0),
                }
            )
        return {
            "active_method": data.get("active_method") or "",
            "auth_base": origins_auth_base,
            "methods": entries,
        }
