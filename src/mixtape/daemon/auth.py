"""Bearer-token authentication dependency for FastAPI routes.

The daemon mints a fresh token at startup and writes it into
``state/api.json``; every client must echo it in
``Authorization: Bearer <token>``. Single-user, single-machine — this
keeps random local processes (or a malicious browser tab on
http://127.0.0.1:<port>) from poking at our API."""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status


class TokenStore:
    """Holds the per-process token. Rebound on each daemon start."""

    def __init__(self) -> None:
        self._token: str | None = None

    def set(self, token: str) -> None:
        self._token = token

    def matches(self, candidate: str) -> bool:
        if self._token is None:
            return False
        return hmac.compare_digest(self._token, candidate)


# Module-level singleton — FastAPI's dependency injection grabs this.
TOKEN = TokenStore()


def require_bearer(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": 'Bearer realm="mixtape"'},
        )
    candidate = authorization[len("bearer "):].strip()
    if not TOKEN.matches(candidate):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
        )
