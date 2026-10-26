"""Raw observations for other engines (abductive_engine DESIGN §2): each a
series, the date it measures, its value, and the date it became public."""
from __future__ import annotations

import csv
import io
from datetime import date

from evals import observations
from src.domains.sources.fred import FREDObservation


def obs(sid, d, v):
    return FREDObservation(obs_date=d, value=v, series_id=sid)


def test_an_unrevised_series_is_public_the_day_after_it_measures():
    history = {"VIXCLS": [obs("VIXCLS", date(2024, 1, 2), 13.2), obs("VIXCLS", date(2024, 1, 3), 14.0)]}
    rows = observations.rows(history, {})
    assert rows == [
        observations.Row("VIXCLS", date(2024, 1, 2), 13.2, date(2024, 1, 3)),
        observations.Row("VIXCLS", date(2024, 1, 3), 14.0, date(2024, 1, 4)),
    ]


def test_a_revised_series_has_a_row_per_published_version():
    vintages = {"CPIAUCSL": {
        "2024-02-16": [["2023-12-01", 100.0], ["2024-01-01", 101.0]],
        "2024-03-16": [["2023-12-01", 100.0], ["2024-01-01", 101.5], ["2024-02-01", 102.0]],
    }}
    rows = observations.rows({}, vintages)
    assert rows == [
        observations.Row("CPIAUCSL", date(2023, 12, 1), 100.0, date(2024, 2, 16)),
        observations.Row("CPIAUCSL", date(2024, 1, 1), 101.0, date(2024, 2, 16)),
        observations.Row("CPIAUCSL", date(2024, 1, 1), 101.5, date(2024, 3, 16)),   # the revision
        observations.Row("CPIAUCSL", date(2024, 2, 1), 102.0, date(2024, 3, 16)),
    ]


def test_a_vintage_series_is_not_also_read_as_unrevised():
    history = {"CPIAUCSL": [obs("CPIAUCSL", date(2024, 1, 1), 101.5)]}
    vintages = {"CPIAUCSL": {"2024-02-16": [["2024-01-01", 101.0]]}}
    assert [r.public for r in observations.rows(history, vintages)] == [date(2024, 2, 16)]


def test_rows_before_the_start_are_left_out():
    history = {"VIXCLS": [obs("VIXCLS", date(1999, 12, 31), 24.6), obs("VIXCLS", date(2000, 1, 3), 24.2)]}
    assert [r.measured for r in observations.rows(history, {}, start=date(2000, 1, 1))] == [date(2000, 1, 3)]


def test_the_export_is_a_csv_of_the_four_fields():
    out = io.StringIO()
    observations.write_csv([observations.Row("UNRATE", date(2024, 1, 1), 3.7, date(2024, 2, 8))], out)
    assert list(csv.reader(io.StringIO(out.getvalue()))) == [
        ["series", "measured", "value", "public"], ["UNRATE", "2024-01-01", "3.7", "2024-02-08"]]
