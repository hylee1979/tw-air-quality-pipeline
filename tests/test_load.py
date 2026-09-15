"""Tests for how the loader reads the command line and expands a range.

The period logic is worth testing before the backfill in step 5 rather than
after it: an off-by-one here is discovered eight thousand iterations in.
Nothing here touches the database.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from aqi_pipeline.load import format_period, parse_args, parse_period, periods_from_args
from aqi_pipeline.sources import SOURCES, TAIPEI

HOURLY = SOURCES["moenv_hourly"]
MONTHLY = SOURCES["moenv_stations"]


def periods(argv: list[str]) -> list[str]:
    """Run the command line the way main does and give back readable periods."""
    args = parse_args(argv)
    source = SOURCES[args.source]
    return [format_period(source, stamp) for stamp in periods_from_args(source, args)]


@pytest.mark.parametrize(
    "source,text",
    [(HOURLY, "2026-09-11T21"), (HOURLY, "2026-01-01T00"), (MONTHLY, "2026-09")],
)
def test_period_round_trips(source, text: str) -> None:
    assert format_period(source, parse_period(source, text)) == text


def test_a_period_is_read_as_taipei_local_time() -> None:
    """The landing-zone path is built from local time, so parsing must match it."""
    assert parse_period(HOURLY, "2026-09-11T21") == datetime(
        2026, 9, 11, 21, tzinfo=TAIPEI
    )


def test_explicit_hours_are_loaded_in_the_order_given() -> None:
    assert periods(
        ["--source", "moenv_hourly", "--hour", "2026-09-11T21", "2026-09-11T23"]
    ) == ["2026-09-11T21", "2026-09-11T23"]


def test_a_range_includes_both_ends() -> None:
    assert periods(
        ["--source", "moenv_hourly", "--from", "2026-09-11T20", "--to", "2026-09-11T22"]
    ) == ["2026-09-11T20", "2026-09-11T21", "2026-09-11T22"]


def test_a_range_of_one_hour_is_that_hour() -> None:
    assert periods(
        ["--source", "moenv_hourly", "--from", "2026-09-11T21", "--to", "2026-09-11T21"]
    ) == ["2026-09-11T21"]


def test_an_hourly_range_crosses_midnight_and_the_month_end() -> None:
    assert periods(
        ["--source", "moenv_hourly", "--from", "2026-09-30T23", "--to", "2026-10-01T01"]
    ) == ["2026-09-30T23", "2026-10-01T00", "2026-10-01T01"]


def test_a_monthly_range_steps_one_month_at_a_time_across_a_year_end() -> None:
    """A month is not a fixed number of days, so stepping it needs care."""
    assert periods(
        ["--source", "moenv_stations", "--month", "2026-11"]
    ) == ["2026-11"]
    assert periods(
        ["--source", "moenv_stations", "--from", "2026-11", "--to", "2027-02"]
    ) == ["2026-11", "2026-12", "2027-01", "2027-02"]


def test_a_monthly_range_does_not_skip_february() -> None:
    assert periods(
        ["--source", "moenv_stations", "--from", "2027-01", "--to", "2027-04"]
    ) == ["2027-01", "2027-02", "2027-03", "2027-04"]


def test_a_backwards_range_is_refused() -> None:
    args = parse_args(
        ["--source", "moenv_hourly", "--from", "2026-09-11T22", "--to", "2026-09-11T20"]
    )
    with pytest.raises(ValueError) as error:
        periods_from_args(HOURLY, args)
    assert "before" in str(error.value)


@pytest.mark.parametrize(
    "argv",
    [
        # Neither form given.
        ["--source", "moenv_hourly"],
        # Both forms given.
        ["--source", "moenv_hourly", "--hour", "2026-09-11T21", "--from", "2026-09-11T20"],
        # Half a range.
        ["--source", "moenv_hourly", "--from", "2026-09-11T20"],
        ["--source", "moenv_hourly", "--to", "2026-09-11T20"],
        # A source that does not exist.
        ["--source", "nope", "--hour", "2026-09-11T21"],
    ],
)
def test_bad_command_lines_are_refused(argv: list[str]) -> None:
    """argparse exits rather than raising, so the test looks for SystemExit."""
    with pytest.raises(SystemExit):
        parse_args(argv)
