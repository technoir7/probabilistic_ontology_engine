"""
Settings — every environment variable this service reads, parsed in one place.

The names are the ones Railway is configured with; keep them. Settings is read
once at startup (Settings.from_env); routes that must see per-request values
(report generation) call it again, which is cheap.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ..model.cadence import Weekly
from .registry import DomainRegistration


def load_dotenv_unless_disabled(environ: Mapping[str, str] = os.environ) -> None:
    # Tests set POE_LOAD_DOTENV=0 so a developer's .env (real API keys) cannot
    # leak into the session and turn mocked tests into network calls.
    if environ.get("POE_LOAD_DOTENV", "1") == "0":
        return
    from dotenv import load_dotenv

    load_dotenv()


def _bool(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    scheduler_enabled: bool
    backfill_days: int
    log_level: str
    fireworks_api_key: str
    fireworks_model: str
    # The raw environment, for per-domain names (<PREFIX>_RUN_HOUR_UTC) and the
    # API keys domain sources read.
    environ: Mapping[str, str] = field(repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> "Settings":
        return cls(
            data_dir=Path(environ.get("POE_DATA_DIR", ".")),
            scheduler_enabled=_bool(environ, "EVIDENCE_SCHEDULER_ENABLED", True),
            backfill_days=_int(environ, "EVIDENCE_BACKFILL_DAYS", 30),
            log_level=environ.get("LOG_LEVEL", "INFO").upper(),
            fireworks_api_key=environ.get("FIREWORKS_API_KEY", ""),
            fireworks_model=environ.get(
                "FIREWORKS_REPORT_MODEL", "accounts/fireworks/models/deepseek-v4-pro"
            ),
            environ=environ,
        )

    def missing_env(self, reg: DomainRegistration) -> list[str]:
        return [name for name in reg.required_env if not self.environ.get(name)]

    def require_env(self, reg: DomainRegistration) -> None:
        missing = self.missing_env(reg)
        if missing:
            raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")

    def run_hour_utc(self, reg: DomainRegistration) -> int:
        return _int(self.environ, f"{reg.env_prefix}_RUN_HOUR_UTC", reg.default_run_hour_utc)

    def startup_window_days(self, reg: DomainRegistration) -> int:
        """How far back the first-start backfill reaches for this domain."""
        if isinstance(reg.cadence, Weekly):
            weeks = _int(self.environ, f"{reg.env_prefix}_BACKFILL_WEEKS", max(self.backfill_days // 7, 8))
            return 7 * weeks
        return self.backfill_days
