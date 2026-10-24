"""
Log output with upstream API keys removed.

FRED and EIA take their keys as query parameters, so any log line or
traceback that quotes a request URL (httpx logs every request at INFO)
would otherwise put the key in the server's logs. Redacting the formatted
line, rather than quieting particular loggers, also catches exception
messages and tracebacks from any library.
"""
from __future__ import annotations

import logging
import re

_SECRET_PARAM = re.compile(r"(\bapi_key=)[^&\s'\"]+", re.IGNORECASE)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return _SECRET_PARAM.sub(r"\1[REDACTED]", super().format(record))


def configure_logging(level: str | int) -> None:
    """Root logging for the server, every line passed through RedactingFormatter."""
    logging.basicConfig(level=level)
    formatter = RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)
