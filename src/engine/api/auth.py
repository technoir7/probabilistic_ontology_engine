"""The admin token that guards operator routes (REFACTOR_SPEC D7)."""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from ..runtime.settings import Settings


def require_admin(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: `Authorization: Bearer <POE_ADMIN_TOKEN>` or 401/503."""
    # Per request, as the report routes read settings; from_env is cheap.
    expected = Settings.from_env().admin_token
    if not expected:
        raise HTTPException(status_code=503, detail="Operator routes are off: set POE_ADMIN_TOKEN to enable them")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Missing or wrong admin token", headers={"WWW-Authenticate": "Bearer"})
