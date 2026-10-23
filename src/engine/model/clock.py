"""The wall clock for stored timestamps."""
from __future__ import annotations

from datetime import datetime, timezone


def naive_utc_now() -> datetime:
    """UTC now without a timezone: the value ``datetime.utcnow()`` gave,
    which the stores, schemas and golden snapshots are written in."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
