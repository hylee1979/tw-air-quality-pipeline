"""Tests for the vocabulary the extract and load steps share.

These cover the pure parts: how a landing-zone path is built, how the data hour
is read out of a real payload, and what the metadata sidecar has to contain.
Nothing here touches the network or the database.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from aqi_pipeline.sources import (
    SOURCES,
    TAIPEI,
    _cwa_observation_time,
    _moenv_publish_time,
    build_metadata,
    metadata_path,
    read_metadata,
    target_path,
)

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
ROOT = Path("data/raw")


def at(year: int, month: int, day: int, hour: int) -> datetime:
    return datetime(year, month, day, hour, tzinfo=TAIPEI)


@pytest.mark.parametrize(
    "source_name,stamp,expected",
    [
        # A single-digit month and day have to be padded, or a lexicographic
        # listing puts month=10 before month=9.
        (
            "moenv_hourly",
            at(2026, 9, 6, 8),
            "data/raw/source=moenv_hourly/year=2026/month=09/day=06/hour08.json",
        ),
        # Midnight is hour00, not hour0 and not an empty component.
        (
            "cwa_hourly",
            at(2026, 1, 1, 0),
            "data/raw/source=cwa_hourly/year=2026/month=01/day=01/hour00.json",
        ),
        # The last hour of a year stays in that year's directory.
        (
            "cwa_hourly",
            at(2026, 12, 31, 23),
            "data/raw/source=cwa_hourly/year=2026/month=12/day=31/hour23.json",
        ),
        # A monthly source has no data hour, so it lands one file per month and
        # the day and hour components are absent entirely.
        (
            "moenv_stations",
            at(2026, 9, 15, 20),
            "data/raw/source=moenv_stations/year=2026/month09.json",
        ),
    ],
)
def test_target_path(source_name: str, stamp: datetime, expected: str) -> None:
    assert str(target_path(ROOT, SOURCES[source_name], stamp)) == expected


def test_metadata_sits_beside_its_payload() -> None:
    payload = target_path(ROOT, SOURCES["moenv_hourly"], at(2026, 9, 6, 8))
    sidecar = metadata_path(payload)
    assert sidecar.parent == payload.parent
    assert sidecar.name == "hour08.metadata.json"


def test_monthly_metadata_follows_the_monthly_name() -> None:
    payload = target_path(ROOT, SOURCES["moenv_stations"], at(2026, 9, 15, 20))
    assert metadata_path(payload).name == "month09.metadata.json"


def test_moenv_publish_time_reads_the_sample() -> None:
    document = json.loads((SAMPLES / "moenv_aqx_p_432.json").read_text())
    assert _moenv_publish_time(document) == at(2026, 9, 6, 16)


def test_cwa_observation_time_reads_the_sample() -> None:
    document = json.loads((SAMPLES / "cwa_O-A0001-001.json").read_text())
    assert _cwa_observation_time(document) == at(2026, 9, 6, 16)


def test_moenv_publish_time_takes_the_latest_not_the_first() -> None:
    """One stale station must not decide the hour the file is filed under."""
    document = [
        {"publishtime": "2026/09/06 15:00:00"},
        {"publishtime": "2026/09/06 16:00:00"},
    ]
    assert _moenv_publish_time(document) == at(2026, 9, 6, 16)


def test_moenv_publish_time_rejects_a_payload_with_no_time() -> None:
    with pytest.raises(ValueError):
        _moenv_publish_time([{"sitename": "基隆", "publishtime": ""}])


def test_metadata_round_trips(tmp_path: Path) -> None:
    payload = b'{"hello": "world"}'
    fetched_at = at(2026, 9, 15, 20)
    path = tmp_path / "hour20.metadata.json"
    path.write_bytes(build_metadata(SOURCES["moenv_hourly"], payload, fetched_at))

    document = read_metadata(path)
    assert document["source"] == "moenv_hourly"
    assert datetime.fromisoformat(document["fetched_at"]) == fetched_at
    # The digest is of the payload, not of the metadata file.
    assert document["sha256"] == (
        "5f8f04f6a3a892aaabbddb6cf273894493773960d4a325b105fee46eef4304f1"
    )


def test_read_metadata_rejects_a_sidecar_missing_a_field(tmp_path: Path) -> None:
    path = tmp_path / "hour20.metadata.json"
    path.write_text(json.dumps({"source": "moenv_hourly"}))
    with pytest.raises(ValueError) as error:
        read_metadata(path)
    # The message has to name what is missing, or the operator has to go and look.
    assert "fetched_at" in str(error.value)
    assert "sha256" in str(error.value)
