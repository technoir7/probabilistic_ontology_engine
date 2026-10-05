"""Errors the engine raises. The API maps them to HTTP status codes."""
from __future__ import annotations


class EngineError(Exception):
    """Base class for failures inside the engine."""


class UnknownValue(EngineError, ValueError):
    """An evidence value is not in its variable's support."""


class InferenceFailed(EngineError):
    """pgmpy could not answer a query for a candidate."""
