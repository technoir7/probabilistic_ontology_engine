"""
Hand-supplied report labels: the art evidence that is not fetched.

A report file holds one item, a list of items, or a crate ({"records": [...]}
and similar keys). Each item labels some variables from one document:

    {"title": "...", "url": "...", "published_at": "2025-04-01",
     "assignments": {"MarketUncertainty": {"value": true, "confidence": 0.8}, ...}}

The rules, which replace the old art package's manual ingest:

* One record per document. Items in the same file with the same date and no
  URL of their own are sections of one report (Hiscox arrived as 25), and
  are merged; counting each section as an observation counted one source 25
  times. A variable labelled in several sections gets the mean probability.
* A label's confidence is the probability it is right: True at 0.8 is
  P(True) = 0.8, False at 0.8 is P(True) = 0.2, clamped to [0.05, 0.95] like
  the other domains' soft evidence. The old ingest ignored confidence.
* A bare true/false counts at DEFAULT_LABEL_CONFIDENCE.
* An item needs a publication date. The old ingest dated undated items
  "now", which moved them on every rebuild.
* Variables a document does not label are MISSING, not False.

Invalid items and unreadable files are reported in ReportBatch.failed and
skipped; the rest still load.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..sources.soft_evidence import build_soft_record
from ...engine.schemas import EvidenceRecord, SourceType
from .domain import DOMAIN_MODULE_ID, VARIABLES, get_variables

# Inside the package so the wheel ships it; POE_ART_MANUAL_DIR points the routes elsewhere.
REPORTS_DIR = Path(__file__).resolve().parent / "report_files"

DEFAULT_LABEL_CONFIDENCE = 0.75
_P_FLOOR, _P_CEIL = 0.05, 0.95
_CONTAINER_KEYS = ("evidence_records", "records", "articles", "items", "evidence", "sources")
_KNOWN = set(VARIABLES)


@dataclass
class ReportBatch:
    records: list[EvidenceRecord] = field(default_factory=list)
    files_scanned: int = 0
    items_found: int = 0
    failed: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Item:
    published: date
    source_ref: str
    labels: dict[str, tuple[float, float]]  # name → (P(True), confidence)


def load_reports(path: Path) -> ReportBatch:
    """Every report under *path* (a .json file or a directory of them), as records."""
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    batch = ReportBatch(files_scanned=len(files))
    for file in files:
        try:
            raw_items = _items_of(json.loads(file.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            batch.failed.append(f"{file.name}: {exc}")
            continue
        batch.items_found += len(raw_items)
        groups: dict[tuple[date, str], list[_Item]] = defaultdict(list)
        for index, raw in enumerate(raw_items):
            try:
                item = _parse_item(raw, file.stem)
            except ValueError as exc:
                batch.failed.append(f"{file.name} item {index}: {exc}")
                continue
            groups[(item.published, item.source_ref)].append(item)
        batch.records.extend(_record(published, ref, items) for (published, ref), items in groups.items())
    batch.records.sort(key=lambda r: r.timestamp)
    return batch


def _items_of(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in _CONTAINER_KEYS:
            if isinstance(payload.get(key), list):
                return payload[key]
        return [payload]
    raise ValueError("expected a JSON object or list")


def _parse_item(raw: Any, file_stem: str) -> _Item:
    if not isinstance(raw, dict):
        raise ValueError("item is not an object")
    published = _published(raw.get("published_at"))
    url = str(raw.get("url") or raw.get("source_url") or "").strip()
    assignments = raw.get("assignments")
    if not isinstance(assignments, dict) or not assignments:
        raise ValueError("assignments must be a non-empty object")
    unknown = sorted(set(assignments) - _KNOWN)
    if unknown:
        raise ValueError(f"unknown variable(s): {', '.join(unknown)}")
    labels = {}
    for name, label in assignments.items():
        parsed = _label(name, label)
        if parsed is not None:
            labels[name] = parsed
    # Sections of one report share a date and have no URL of their own.
    return _Item(published, url or f"report:{file_stem}", labels)


def _published(value: Any) -> date:
    if not value:
        raise ValueError("published_at is required (an undated label cannot be placed in time)")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ValueError(f"published_at {value!r} is not an ISO date") from exc


def _label(name: str, label: Any) -> tuple[float, float] | None:
    """(P(True), confidence), or None when the label says "unknown"."""
    confidence: Any = DEFAULT_LABEL_CONFIDENCE
    if isinstance(label, dict):
        confidence = label.get("confidence", DEFAULT_LABEL_CONFIDENCE)
        label = label.get("value", label.get("signal"))
    if label is None:
        return None
    if not isinstance(label, bool):
        raise ValueError(f"{name}: value must be true, false or null, got {label!r}")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.5 <= confidence <= 1.0:
        raise ValueError(f"{name}: confidence must be a number in [0.5, 1], got {confidence!r}")
    p_true = confidence if label else 1.0 - confidence
    return min(_P_CEIL, max(_P_FLOOR, p_true)), float(confidence)


def _record(published: date, source_ref: str, items: list[_Item]) -> EvidenceRecord:
    probabilities: dict[str, list[float]] = defaultdict(list)
    confidences: dict[str, list[float]] = defaultdict(list)
    for item in items:
        for name, (p_true, confidence) in item.labels.items():
            probabilities[name].append(p_true)
            confidences[name].append(confidence)
    p = {name: sum(ps) / len(ps) for name, ps in probabilities.items()}
    return build_soft_record(
        module_id=DOMAIN_MODULE_ID,
        variables=get_variables(),
        states=[(name, p.get(name, 0.5) > 0.5, p.get(name, 0.5)) for name in VARIABLES],
        confidence={name: sum(cs) / len(cs) for name, cs in confidences.items()},
        target_date=published,
        source_ref=source_ref,
        missing=[name for name in VARIABLES if name not in p],
        source_type=SourceType.MANUAL,
    )
