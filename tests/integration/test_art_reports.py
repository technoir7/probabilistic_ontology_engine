"""
Hand-supplied art report labels (art_prestige_regime_v1/reports.py).

The rules that replace the old manual ingest: one record per report, not one
per section; a label's confidence becomes the probability; a record needs a
publication date (it is never dated "today"); unlabelled variables are MISSING.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.domains.art_prestige_regime_v1.domain import get_variables
from src.domains.art_prestige_regime_v1.reports import REPORTS_DIR, load_reports
from src.engine.schemas import MissingnessType, SourceType

NAMES = {v.variable_id: name for name, v in get_variables().items()}


def _assignments(record) -> dict[str, tuple[str, float | None]]:
    return {
        NAMES[a.variable_id]: (a.missingness.value, (a.probabilities or {}).get(True))
        for a in record.observed_assignments
    }


def _write(tmp_path: Path, name: str, payload) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _label(value, confidence):
    return {"value": value, "confidence": confidence, "rationale": "..."}


def test_sections_of_one_report_become_one_record(tmp_path):
    _write(tmp_path, "hiscox.json", [
        {"title": "Hiscox intro", "url": "", "published_at": "2025-04-01",
         "assignments": {"MarketUncertainty": _label(True, 0.9)}},
        {"title": "Hiscox chapter 2", "url": "", "published_at": "2025-04-01",
         "assignments": {"MarketUncertainty": _label(True, 0.7), "AuthenticityPremium": _label(False, 0.8)}},
    ])
    batch = load_reports(tmp_path)
    assert (batch.files_scanned, batch.items_found, batch.failed) == (1, 2, [])
    [record] = batch.records
    got = _assignments(record)
    assert got["MarketUncertainty"] == ("SOFT_OBSERVED", pytest.approx(0.8))  # mean of 0.9 and 0.7
    assert got["AuthenticityPremium"] == ("SOFT_OBSERVED", pytest.approx(0.2))  # False at 0.8
    assert got["BiennialFatigue"] == ("MISSING", None)
    assert record.timestamp == datetime(2025, 4, 1, tzinfo=timezone.utc)
    assert record.source_type == SourceType.MANUAL


def test_articles_with_their_own_url_stay_separate(tmp_path):
    _write(tmp_path, "artnet.json", {"evidence_records": [
        {"title": "a", "url": "https://news.example/a", "published_at": "2026-05-21",
         "assignments": {"MarketUncertainty": _label(True, 0.6)}},
        {"title": "b", "url": "https://news.example/b", "published_at": "2026-05-21",
         "assignments": {"MarketUncertainty": _label(False, 0.6)}},
    ]})
    assert len(load_reports(tmp_path).records) == 2


def test_probabilities_are_clamped_and_nulls_are_missing(tmp_path):
    _write(tmp_path, "x.json", {"title": "t", "published_at": "2026-01-01", "assignments": {
        "AIImageSaturation": _label(True, 0.99),
        "MarketUncertainty": None,
        "AuthenticityPremium": True,  # bare label: default confidence
    }})
    [record] = load_reports(tmp_path).records
    got = _assignments(record)
    assert got["AIImageSaturation"][1] == pytest.approx(0.95)
    assert got["MarketUncertainty"] == ("MISSING", None)
    assert got["AuthenticityPremium"][1] == pytest.approx(0.75)


@pytest.mark.parametrize("item, reason", [
    ({"title": "t", "assignments": {"MarketUncertainty": True}}, "published_at"),
    ({"title": "t", "published_at": "2026-01-01", "assignments": {"NotAVariable": True}}, "NotAVariable"),
    ({"title": "t", "published_at": "2026-01-01", "assignments": {"MarketUncertainty": _label(True, 1.4)}}, "confidence"),
])
def test_invalid_items_are_reported_not_ingested(tmp_path, item, reason):
    _write(tmp_path, "bad.json", [item, {"title": "ok", "published_at": "2026-02-01",
                                         "assignments": {"MarketUncertainty": True}}])
    batch = load_reports(tmp_path)
    assert len(batch.records) == 1
    [failure] = batch.failed
    assert "bad.json" in failure and reason in failure


def test_unreadable_file_is_reported(tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    batch = load_reports(tmp_path)
    assert batch.records == [] and "broken.json" in batch.failed[0]


def test_evidence_ids_are_stable_across_loads(tmp_path):
    _write(tmp_path, "x.json", {"title": "t", "published_at": "2026-01-01",
                                "assignments": {"MarketUncertainty": True}})
    assert load_reports(tmp_path).records[0].evidence_id == load_reports(tmp_path).records[0].evidence_id


def test_the_shipped_reports_load():
    batch = load_reports(REPORTS_DIR)
    assert batch.files_scanned == 7 and batch.items_found == 70
    # Hiscox (25 sections) and the 2025 market report (11) collapse to one record each.
    assert len(batch.records) < 40
    # Three items carry no publication date; they are reported, not dated today.
    assert len(batch.failed) == 3 and all("published_at" in f for f in batch.failed)
    soft = [a for r in batch.records for a in r.observed_assignments if a.missingness == MissingnessType.SOFT_OBSERVED]
    assert all(0.05 <= a.probabilities[True] <= 0.95 for a in soft)
