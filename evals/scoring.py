"""
Scores a replay against the events fixed in `evals/README.md` before it ran.

Pure functions of the replay's rows, so each measure can be tested.
"""
from __future__ import annotations

import random
from collections import Counter
from datetime import date, timedelta
from typing import Iterable

WINDOW_WEEKS = 26

# (name, the day it began), as fixed in the plan.
EVENTS = [
    ("2008 recession", date(2007, 12, 1)),
    ("Lehman Brothers fails", date(2008, 9, 15)),
    ("Taper tantrum", date(2013, 5, 22)),
    ("First hike after zero rates", date(2015, 12, 16)),
    ("Quantitative tightening begins", date(2017, 10, 1)),
    ("COVID crash", date(2020, 2, 1)),
    ("2022 hiking cycle", date(2022, 3, 16)),
    ("Quantitative tightening resumes", date(2022, 6, 1)),
    ("ChatGPT released", date(2022, 11, 30)),
    ("Silicon Valley Bank fails", date(2023, 3, 10)),
]

# Question 4: the family expected to lead each period (a stated expectation).
EXPECTED = [
    ("2008–09", date(2008, 1, 1), date(2009, 12, 31), {"T_credit", "T_recession"}),
    ("2022–23", date(2022, 1, 1), date(2023, 12, 31), {"T_monetary", "T_recession"}),
    ("2023–24", date(2023, 1, 1), date(2024, 12, 31), {"T_ai_boom"}),
]


def _d(text: str) -> date:
    return date.fromisoformat(text)


def family_changes(rows: list[dict]) -> list[dict]:
    out = []
    for prev, row in zip(rows, rows[1:]):
        if row["family"] != prev["family"]:
            out.append({"week": row["week"], "from": prev["family"], "to": row["family"]})
    return out


def _after(event_day: date, week: date, window_weeks: int) -> bool:
    return event_day < week <= event_day + timedelta(weeks=window_weeks)


def events_caught(changes: list[dict], events=EVENTS, window_weeks: int = WINDOW_WEEKS) -> dict[str, bool]:
    return {name: any(_after(day, _d(c["week"]), window_weeks) for c in changes) for name, day in events}


def changes_away_from_events(changes: list[dict], events=EVENTS, window_weeks: int = WINDOW_WEEKS) -> list[dict]:
    return [c for c in changes if not any(_after(day, _d(c["week"]), window_weeks) for _, day in events)]


def chance(weeks: list[str], n_changes: int, events=EVENTS, window_weeks: int = WINDOW_WEEKS,
           draws: int = 10_000, seed: int = 0) -> dict:
    """The same number of changes at random weeks: the share of events they
    catch, on average, and the share of draws catching each count."""
    rng = random.Random(seed)
    days = [_d(w) for w in weeks]
    caught_counts = []
    for _ in range(draws):
        picked = rng.sample(days, min(n_changes, len(days)))
        caught_counts.append(sum(any(_after(day, w, window_weeks) for w in picked) for _, day in events))
    return {"mean_share_caught": sum(caught_counts) / (draws * len(events)),
            "distribution": dict(sorted(Counter(caught_counts).items()))}


def p_at_least(distribution: dict[int, int], observed: int) -> float:
    total = sum(distribution.values())
    return sum(n for k, n in distribution.items() if k >= observed) / total


def fit_gap(rows: Iterable[dict]) -> dict:
    """Average nats per week by which the leading structure's prediction of
    the week beats independent signals, over weeks with every signal seen."""
    gaps = [r["leader_ll"] - r["independent_ll"] for r in rows if r["observed"] == 8]
    return {"weeks": len(gaps), "mean_gap_nats": round(sum(gaps) / len(gaps), 4) if gaps else None}


def weeks_led(rows: list[dict], start: date, end: date) -> dict[str, int]:
    return dict(Counter(r["family"] for r in rows if start <= _d(r["week"]) <= end))
