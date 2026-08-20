"""Security primitives for EflortableJD.

Credentials are stored as salted PBKDF2-HMAC-SHA256 verifiers, never as
plaintext. Access decisions are explicit and auditable. TLS is intentionally
left to the deployment boundary or a future native transport layer.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

PBKDF2_ITERATIONS = 240_000


class AuthenticationError(PermissionError):
    pass


class AuthorizationError(PermissionError):
    pass


class RateLimitError(PermissionError):
    pass


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def hash_secret(secret: str, *, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64(salt)}${_b64(digest)}"


def verify_secret(secret: str, encoded: str) -> bool:
    try:
        algorithm, iteration_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iteration_text)
        expected = _unb64(digest_text)
        actual = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), _unb64(salt_text), iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class Principal:
    subject: str
    tenant: str
    roles: frozenset[str]
    token_id: str | None = None


@dataclass
class Role:
    name: str
    permissions: set[str] = field(default_factory=set)


class CredentialStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        if self.path.exists():
            os.chmod(self.path, 0o600)
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self._data = {"users": {}, "tokens": {}}
            self._persist()
        self._mtime_ns = self.path.stat().st_mtime_ns

    def _refresh(self) -> None:
        current_mtime = self.path.stat().st_mtime_ns
        if current_mtime != self._mtime_ns:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
            self._mtime_ns = current_mtime

    def _persist(self) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self._data, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)
        os.chmod(self.path, 0o600)
        self._mtime_ns = self.path.stat().st_mtime_ns

    def create_user(self, username: str, password: str, *, tenant: str = "default", roles: Iterable[str] = ("reader",)) -> None:
        if not username or not password or not tenant:
            raise ValueError("username, password, and tenant are required")
        with self._lock:
            if username in self._data["users"]:
                raise ValueError("user already exists")
            self._data["users"][username] = {"password": hash_secret(password), "tenant": tenant, "roles": sorted(set(roles)), "disabled": False}
            self._persist()

    def disable_user(self, username: str) -> None:
        with self._lock:
            self._data["users"][username]["disabled"] = True
            self._persist()

    def authenticate_password(self, username: str, password: str) -> Principal:
        with self._lock:
            user = self._data["users"].get(username)
            if not user or user.get("disabled") or not verify_secret(password, user["password"]):
                raise AuthenticationError("invalid credentials")
            return Principal(username, user["tenant"], frozenset(user["roles"]))

    def issue_token(self, principal: Principal, *, ttl_seconds: int = 3600) -> str:
        token = secrets.token_urlsafe(32)
        token_id = secrets.token_hex(12)
        with self._lock:
            self._data["tokens"][token_id] = {"hash": hash_secret(token), "subject": principal.subject, "tenant": principal.tenant, "roles": sorted(principal.roles), "expires": time.time() + ttl_seconds, "revoked": False}
            self._persist()
        return f"{token_id}.{token}"

    def authenticate_token(self, token: str) -> Principal:
        try:
            token_id, secret = token.split(".", 1)
        except ValueError as exc:
            raise AuthenticationError("invalid token") from exc
        with self._lock:
            self._refresh()
            record = self._data["tokens"].get(token_id)
            if not record or record.get("revoked") or float(record["expires"]) < time.time() or not verify_secret(secret, record["hash"]):
                raise AuthenticationError("invalid token")
            return Principal(record["subject"], record["tenant"], frozenset(record["roles"]), token_id)

    def revoke_token(self, token: str) -> None:
        token_id = token.split(".", 1)[0]
        with self._lock:
            if token_id in self._data["tokens"]:
                self._data["tokens"][token_id]["revoked"] = True
                self._persist()


class SecurityManager:
    DEFAULT_ROLES = {
        "reader": {"read"},
        "writer": {"read", "write"},
        "admin": {"read", "write", "admin"},
    }

    def __init__(self, credentials_path: str | Path) -> None:
        self.credentials = CredentialStore(credentials_path)
        self.roles = {name: Role(name, set(permissions)) for name, permissions in self.DEFAULT_ROLES.items()}

    def authenticate_bearer(self, token: str) -> Principal:
        return self.credentials.authenticate_token(token)

    def authorize(self, principal: Principal, action: str, collection: str, *, tenant: str | None = None) -> None:
        if tenant is not None and tenant != principal.tenant and "admin" not in principal.roles:
            raise AuthorizationError("cross-tenant access denied")
        required = "admin" if action == "admin" else action
        if not any(required in self.roles.get(role, Role(role)).permissions for role in principal.roles):
            raise AuthorizationError(f"role is not authorized for {action}")
        if not collection or collection.startswith("_"):
            raise AuthorizationError("invalid collection name")

    @staticmethod
    def scoped_collection(principal: Principal, collection: str) -> str:
        if not collection or "/" in collection or collection.startswith("_"):
            raise AuthorizationError("invalid collection name")
        return f"{principal.tenant}/{collection}"


class TokenBucket:
    def __init__(self, capacity: float, refill_per_second: float) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self.tokens = capacity
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def consume(self, amount: float = 1.0) -> bool:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.refill_per_second)
            self.updated = now
            if self.tokens < amount:
                return False
            self.tokens -= amount
            return True


class RateLimiter:
    def __init__(self, capacity: int = 100, refill_per_second: float = 25.0) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        with self._lock:
            bucket = self._buckets.setdefault(key, TokenBucket(self.capacity, self.refill_per_second))
        if not bucket.consume():
            raise RateLimitError("rate limit exceeded")


class AuditLogger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._previous_hash = "0" * 64
        if not self.path.exists():
            self.path.touch()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    self._previous_hash = json.loads(line)["hash"]
                except (ValueError, KeyError, TypeError):
                    raise ValueError("audit log is corrupt")
        os.chmod(self.path, 0o600)

    def record(self, *, principal: Principal | None, action: str, resource: str, outcome: str, metadata: dict[str, Any] | None = None) -> None:
        event = {"timestamp": time.time(), "subject": principal.subject if principal else None, "tenant": principal.tenant if principal else None, "action": action, "resource": resource, "outcome": outcome, "metadata": metadata or {}, "previous_hash": self._previous_hash}
        digest = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        event["hash"] = digest
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._previous_hash = digest
