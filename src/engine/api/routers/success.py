"""What predicts an artist's success next year, four ways (REFACTOR_SPEC
D31); only art has it."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...runtime.success import current_success
from .. import context
from ..success_dto import RewardedOut, SuccessKindOut, SuccessOut, SuccessSnapshotOut, ThemeTestOut

router = APIRouter()


@router.get("/v1/success", response_model=SuccessOut)
async def success(domain: str = Query(...)) -> SuccessOut:
    key = domain.lower()
    if key not in context.DOMAIN_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{domain}'")
    s = current_success(key)
    if s is None:
        return SuccessOut(domain=key, success=None)
    return SuccessOut(domain=key, success=SuccessSnapshotOut(
        year=s.year, forecast_for=s.forecast_for,
        kinds={k: SuccessKindOut(
            key=v.key, title=v.title, outcome=v.outcome, leader=list(v.leader), leader_since=v.leader_since,
            gain=v.gain, mechanisms=list(v.mechanisms), effects={f"{f}={lv}": e for (f, lv), e in v.effects.items()},
            dealt={f: list(g) for f, g in v.dealt.items()}, placebo=v.placebo,
            placebo_fair=v.placebo_fair, most_raised=list(v.most_raised),
            years=list(v.years)) for k, v in s.kinds.items()},
        rewarded=[RewardedOut(kind=r.kind, name=r.name, approvals=r.approvals, disapprovals=r.disapprovals,
                              approved=list(r.approved), disapproved=list(r.disapproved)) for r in s.rewarded],
        themes={k: ThemeTestOut(
            leader=list(t.leader), leader_since=t.leader_since, gain=t.gain, gain_without=t.gain_without,
            effects={f"{f}={lv}": e for (f, lv), e in t.effects.items()}, dealt={f: list(g) for f, g in t.dealt.items()},
            placebo=t.placebo, year=t.year, best=list(t.best), worst=list(t.worst)) for k, t in s.themes.items()}))
