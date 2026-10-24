"""
Cadence — when a domain's evidence is dated and fetched. The one copy of the
calendar rules: the scheduler, the startup backfill and both API ingest routes
all ask the domain's Cadence, so they can no longer disagree (REFACTOR_SPEC B8).

Weekly evidence is dated by the Sunday that ends its week (decision D12) and
fetched on the Monday after. Monthly evidence is dated by the month's last
day and fetched on the 1st after.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

SUNDAY = 6


@dataclass(frozen=True)
class Daily:
    """One record per day, dated that day; runs every day for the day
    *lag_days* back, the latest its source has published (yesterday unless
    the source is late)."""

    lag_days: int = 1

    def align(self, day: date) -> date:
        return day

    def default_target(self, today: date) -> date:
        return today - timedelta(days=self.lag_days)

    def window_targets(self, days: int, today: date) -> list[date]:
        """The latest *days* published days before *today*, oldest first."""
        latest = self.default_target(today)
        return [latest - timedelta(days=delta) for delta in range(days - 1, -1, -1)]

    def next_run(self, now: datetime, run_hour_utc: int) -> datetime:
        nxt = now.replace(hour=run_hour_utc, minute=0, second=0, microsecond=0)
        return nxt if nxt > now else nxt + timedelta(days=1)


@dataclass(frozen=True)
class Weekly:
    """One record per week, dated by the week's last day (*week_end* weekday)."""

    week_end: int = SUNDAY

    def align(self, day: date) -> date:
        """The week end on or before *day*."""
        return day - timedelta(days=(day.weekday() - self.week_end) % 7)

    def default_target(self, today: date) -> date:
        """The latest week that has fully ended before *today*."""
        return self.align(today - timedelta(days=1))

    def window_targets(self, days: int, today: date) -> list[date]:
        """Each week end touched by the *days* before *today*, oldest first."""
        return sorted({self.align(today - timedelta(days=delta)) for delta in range(days, 0, -1)})

    def next_run(self, now: datetime, run_hour_utc: int) -> datetime:
        """The run hour on the day after a week end (Monday for Sunday weeks)."""
        run_weekday = (self.week_end + 1) % 7
        days_ahead = (run_weekday - now.weekday()) % 7
        nxt = (now + timedelta(days=days_ahead)).replace(
            hour=run_hour_utc, minute=0, second=0, microsecond=0
        )
        return nxt if nxt > now else nxt + timedelta(days=7)


@dataclass(frozen=True)
class Monthly:
    """One record per calendar month, dated by its last day."""

    def align(self, day: date) -> date:
        """The month end on or before *day*."""
        next_month_first = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
        month_end = next_month_first - timedelta(days=1)
        return month_end if day == month_end else day.replace(day=1) - timedelta(days=1)

    def default_target(self, today: date) -> date:
        """The latest month that has fully ended before *today*."""
        return self.align(today - timedelta(days=1))

    def window_targets(self, days: int, today: date) -> list[date]:
        """Each month end touched by the *days* before *today*, oldest first."""
        return sorted({self.align(today - timedelta(days=delta)) for delta in range(days, 0, -1)})

    def next_run(self, now: datetime, run_hour_utc: int) -> datetime:
        """The run hour on the 1st of a month."""
        first = now.replace(day=1, hour=run_hour_utc, minute=0, second=0, microsecond=0)
        if first > now:
            return first
        return (first + timedelta(days=32)).replace(day=1)


Cadence = Daily | Weekly | Monthly
