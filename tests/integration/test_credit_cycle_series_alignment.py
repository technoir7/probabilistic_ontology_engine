"""
REFACTOR_SPEC B15: RefinancingStress combines DGS5 and HY spreads. The two
series publish on different calendars (Treasury holidays differ from ICE's),
so they must be paired by date. A day only one series has must not shift the
pairing of every later observation.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from src.domains.credit_cycle_v1.ingestion.fred_client import FREDObservation
from src.domains.credit_cycle_v1.ingestion.pipeline import compute_snapshot

TARGET = date(2026, 3, 2)


def _series(series_id: str, days: list[date], f) -> list[FREDObservation]:
    # Newest first, the order the FRED client returns.
    return [FREDObservation(obs_date=d, value=f(i), series_id=series_id) for i, d in enumerate(days)]


def test_refinancing_stress_pairs_observations_by_date():
    days = [TARGET - timedelta(days=i) for i in range(120)]
    dgs5 = _series("DGS5", days, lambda i: 4.0 + 0.5 * math.sin(i / 5))
    hy = _series("BAMLH0A0HYM2", days, lambda i: 3.0 + 0.8 * math.cos(i / 7))
    aligned = compute_snapshot({"DGS5": dgs5, "BAMLH0A0HYM2": hy}, TARGET).signals.get("RefinancingStress")

    # A Treasury holiday: drop one recent DGS5 day that HY still has.
    holiday = days[3]
    dgs5_with_gap = [o for o in dgs5 if o.obs_date != holiday]
    hy_without_holiday = [o for o in hy if o.obs_date != holiday]

    with_gap = compute_snapshot({"DGS5": dgs5_with_gap, "BAMLH0A0HYM2": hy}, TARGET).signals.get("RefinancingStress")
    both_dropped = compute_snapshot(
        {"DGS5": dgs5_with_gap, "BAMLH0A0HYM2": hy_without_holiday}, TARGET
    ).signals.get("RefinancingStress")

    assert aligned is not None
    assert with_gap == both_dropped
