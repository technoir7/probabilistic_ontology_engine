"""Upstream API keys travel in query strings; no log line may carry one."""
import logging

from src.engine.runtime.log_redaction import RedactingFormatter


def _format(msg: str, *, exc: BaseException | None = None) -> str:
    record = logging.LogRecord("httpx", logging.INFO, __file__, 1, msg, None,
                               (type(exc), exc, None) if exc else None)
    return RedactingFormatter("%(name)s: %(message)s").format(record)


def test_api_key_in_a_request_url_is_redacted():
    line = _format("GET https://api.stlouisfed.org/fred/series/observations"
                   "?series_id=UNRATE&api_key=abc123def456&file_type=json")
    assert "abc123def456" not in line
    assert "api_key=[REDACTED]&file_type=json" in line
    assert "series_id=UNRATE" in line


def test_api_key_in_an_exception_is_redacted():
    try:
        raise RuntimeError("HTTP 500 for url 'https://api.eia.gov/series/?api_key=SECRETKEY'")
    except RuntimeError as exc:
        line = _format("ingest failed", exc=exc)
    assert "SECRETKEY" not in line
    assert "api_key=[REDACTED]" in line


def test_lines_without_a_key_are_unchanged():
    assert _format("learn() complete: domain=lm") == "httpx: learn() complete: domain=lm"


def test_a_hyphenated_api_key_is_redacted():
    # The Guardian and the NYT spell the parameter api-key.
    line = _format("GET https://api.nytimes.com/svc/archive/v1/2020/1.json?api-key=NYTSECRET "
                   "and https://content.guardianapis.com/search?section=artanddesign&api-key=GSECRET&page=2")
    assert "NYTSECRET" not in line and "GSECRET" not in line
    assert "api-key=[REDACTED]&page=2" in line
