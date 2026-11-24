"""Authentication: bcrypt passwords, 1-hour HS256 JWTs (design decision 10).

The token carries only the user id. Role, projects and grants are loaded from the database on every
request, so a demotion or revocation applies immediately — the token is never a permission cache.
"""

from __future__ import annotations

import os
import secrets
import time
from collections import defaultdict, deque

import bcrypt
import jwt

TOKEN_TTL_SECONDS = 3600
_ALGORITHM = "HS256"
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt()).decode()

# A random secret per process if none is configured: tokens stop working on restart, which is fine
# for local development and safe by default. Set JWT_SECRET in any shared deployment.
_SECRET = os.environ.get("JWT_SECRET") or secrets.token_urlsafe(48)


def demo_password() -> str | None:
    """The shared demo password for seeded users. A test value, recorded in .env.example."""
    return os.environ.get("DEMO_PASSWORD", "xyz-demo-2026")


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "true").lower() in {"1", "true", "yes"}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    # Always run one bcrypt check so unknown emails take as long as wrong passwords.
    ok = bcrypt.checkpw(password.encode(), (password_hash or _DUMMY_HASH).encode())
    return ok and password_hash is not None


def create_token(user_id: str, *, now: float | None = None) -> str:
    now = now or time.time()
    return jwt.encode({"sub": user_id, "iat": int(now), "exp": int(now) + TOKEN_TTL_SECONDS},
                      _SECRET, algorithm=_ALGORITHM)


def decode_token(token: str) -> str:
    """Returns the user id. Raises jwt.InvalidTokenError on a bad, expired or tampered token."""
    payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM], options={"require": ["sub", "exp"]})
    return payload["sub"]


class LoginRateLimiter:
    """At most ``max_failures`` failed logins per email per ``window`` seconds (in-memory, per process)."""

    def __init__(self, max_failures: int = 10, window: float = 600):
        self.max_failures, self.window = max_failures, window
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def blocked(self, key: str) -> bool:
        q = self._failures[key]
        cutoff = time.monotonic() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return len(q) >= self.max_failures

    def record_failure(self, key: str) -> None:
        self._failures[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
