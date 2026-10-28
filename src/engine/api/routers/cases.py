"""Cases mode (REFACTOR_SPEC D29): mechanisms judged across many small
histories at once; only art has case sets."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...runtime.cases import compute_case_reports
from .. import context
from ..dto import CaseForecastOut, CaseSetOut, CasesOut, CaseShiftOut, CaseYearOut

router = APIRouter()


@router.get("/v1/cases", response_model=CasesOut)
async def cases(domain: str = Query(...)) -> CasesOut:
    key = domain.lower()
    if key not in context.DOMAIN_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{domain}'")
    return CasesOut(domain=key, case_sets=[_case_set(r) for r in compute_case_reports(key)])


def _forecast(f) -> CaseForecastOut:
    return CaseForecastOut(case=f.case, label=f.label, own_past=list(f.own_past), with_leader=list(f.with_leader))


def _case_set(r) -> CaseSetOut:
    return CaseSetOut(
        key=r.key, title=r.title, outcome=r.outcome, pool=list(r.pool), leader=list(r.leader),
        shifts=[CaseShiftOut(year=s.year, frm=list(s.frm), to=list(s.to)) for s in r.shifts],
        years=[CaseYearOut(year=y.year, engine=y.engine, own_past=y.own_past, cases=y.cases) for y in r.years],
        gain=r.gain, forecast_year=r.forecast_year,
        likeliest=[_forecast(f) for f in r.likeliest], most_raised=[_forecast(f) for f in r.most_raised],
    )
