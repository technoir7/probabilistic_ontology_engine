"""Recent evidence records."""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Query, Request

from .. import context, poea_dynamic
from ..dto import (
    OntologyMode,
    EvidenceRecordOut,
    EvidenceOut,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/v1/evidence/recent", response_model=EvidenceOut)
async def evidence_recent(
    request: Request,
    domain: str = Query("ng"),
    limit: int = Query(20, ge=1, le=100),
    ontology_mode: OntologyMode = Query("apriori"),
) -> EvidenceOut:
    engine, domain_id, display_name = context.resolve_domain(domain, request.app.state)
    if ontology_mode == "dynamic" and poea_dynamic.is_dynamic_available(domain.lower()):
        return EvidenceOut.model_validate(
            poea_dynamic.build_recent_evidence(display_name, limit)
        )
    raw_records = engine.evidence_store.load_recent(domain_id, limit)

    records: list[EvidenceRecordOut] = []
    for r in raw_records:
        confidence: float = r.get("confidence", 1.0)
        assignments: list = r.get("assignments", [])
        n_vars = len([a for a in assignments if a.get("missingness", "OBSERVED") == "OBSERVED"])

        if confidence > 0.8:
            strength: Literal["strong", "shift", "weak"] = "strong"
        elif confidence > 0.4:
            strength = "shift"
        else:
            strength = "weak"

        source_ref: str = r.get("source_ref", "")
        description = source_ref if source_ref else f"Evidence record {r['evidence_id'][:8]}"

        records.append(EvidenceRecordOut(
            id=r["evidence_id"],
            timestamp=r["timestamp"],
            description=description,
            impact_delta=confidence,
            strength=strength,
            variables_updated=n_vars if n_vars > 0 else None,
        ))

    return EvidenceOut(domain=display_name, records=records)
