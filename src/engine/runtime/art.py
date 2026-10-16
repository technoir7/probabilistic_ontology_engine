"""
The art domain's supplied evidence: report files on disk.

Lives in runtime because the API may not import domains (import contracts);
the parsing rules are in domains/art_prestige_regime_v1/reports.py.
"""
from __future__ import annotations

from pathlib import Path

from ...domains.art_prestige_regime_v1.reports import REPORTS_DIR, ReportBatch, load_reports
from .settings import Settings

__all__ = ["ReportBatch", "load_reports", "reports_dir"]


def reports_dir(settings: Settings) -> Path:
    """Where report files are read from: POE_ART_MANUAL_DIR, else the repo's data/art_reports."""
    return settings.art_manual_dir or REPORTS_DIR
