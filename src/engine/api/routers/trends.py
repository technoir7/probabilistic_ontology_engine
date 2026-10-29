"""This year's trends in what is written about a domain (REFACTOR_SPEC
D30); only art has any."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...runtime.trends import current_trends
from .. import context
from ..dto import TrendListsOut, TrendOut, TrendsOut

router = APIRouter()


@router.get("/v1/trends", response_model=TrendsOut)
async def trends(domain: str = Query(...)) -> TrendsOut:
    key = domain.lower()
    if key not in context.DOMAIN_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{domain}'")
    t = current_trends(key)
    if t is None:
        return TrendsOut(domain=key, trends=None)
    return TrendsOut(domain=key, trends=TrendListsOut(
        year=t.year, before=t.before, years=list(t.years), all_writers=list(t.all_writers),
        lists={k: list(v) for k, v in t.lists.items()},
        trends={k: TrendOut(key=x.key, name=x.name, start=x.start, words=list(x.words), writers=list(x.writers),
                            papers=list(x.papers), verdicts=list(x.verdicts), sample=list(x.sample))
                for k, x in t.trends.items()},
    ))
