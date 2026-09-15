"""What the sources are and where their payloads land.

This module holds the vocabulary the extract and load steps share: which APIs
exist, how a landing-zone path is built, and what the metadata file beside each
payload contains. Keeping the writer and the reader of that metadata in one
place stops the two ends of the contract from drifting apart.

The decisions behind it are recorded in docs/decisionlog.md under "Extractor"
and "Raw layer".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# Written to by the extractor, read back by the loader.
LANDING_ROOT = Path("data/raw")

# Both platforms report in local time. The air-quality feed omits the offset, so
# it has to be attached; the weather feed states it.
TAIPEI = ZoneInfo("Asia/Taipei")


def _moenv_publish_time(document: Any) -> datetime:
    """Read the data hour from an air-quality payload.

    The response is a flat list, one entry per station, each carrying the same
    publishtime. The maximum is taken rather than the first entry so that a
    single stale station cannot decide the path.
    """
    stamps = [row["publishtime"] for row in document if row.get("publishtime")]
    if not stamps:
        raise ValueError("no publishtime in payload")
    return datetime.strptime(max(stamps), "%Y/%m/%d %H:%M:%S").replace(tzinfo=TAIPEI)


def _cwa_observation_time(document: Any) -> datetime:
    """Read the data hour from a weather payload.

    Timestamps here are ISO 8601 and carry the +08:00 offset.
    """
    stamps = [
        station["ObsTime"]["DateTime"]
        for station in document["records"]["Station"]
        if station.get("ObsTime", {}).get("DateTime")
    ]
    if not stamps:
        raise ValueError("no ObsTime in payload")
    return datetime.fromisoformat(max(stamps)).astimezone(TAIPEI)


@dataclass(frozen=True)
class Source:
    """One API this module knows how to fetch.

    Attributes:
        name: Short slug used in the landing-zone path.
        url: Endpoint, without the key.
        key_param: Query parameter that carries the API key. The two platforms
            differ here: the air-quality platform uses api_key, the weather
            platform uses Authorization.
        key_env: Environment variable holding the key.
        granularity: "hour" for the readings, "month" for the station master
            data, which is effectively static and fetched on its own schedule.
        data_time: Reads the hour the data describes out of the parsed payload.
            None for a source that carries no timestamp, in which case the fetch
            time is used instead.
        params: Extra query parameters. A limit is sent explicitly so that a
            change to the platform default cannot silently truncate the result.
    """

    name: str
    url: str
    key_param: str
    key_env: str
    granularity: str
    data_time: Callable[[Any], datetime] | None = None
    params: dict[str, str] = field(default_factory=dict)


SOURCES: dict[str, Source] = {
    "moenv_hourly": Source(
        name="moenv_hourly",
        url="https://data.moenv.gov.tw/api/v2/aqx_p_432",
        key_param="api_key",
        key_env="MOENV_API_KEY",
        granularity="hour",
        data_time=_moenv_publish_time,
        params={"limit": "1000"},
    ),
    "moenv_stations": Source(
        name="moenv_stations",
        url="https://data.moenv.gov.tw/api/v2/aqx_p_07",
        key_param="api_key",
        key_env="MOENV_API_KEY",
        granularity="month",
        data_time=None,
        params={"limit": "1000"},
    ),
    "cwa_hourly": Source(
        name="cwa_hourly",
        url="https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0001-001",
        key_param="Authorization",
        key_env="CWA_API_KEY",
        granularity="hour",
        data_time=_cwa_observation_time,
    ),
}

def target_path(root: Path, source: Source, stamp: datetime) -> Path:
    """Build the landing-zone path for one source and one timestamp.

    Hourly sources land at:

        <root>/source=<name>/year=2026/month=09/day=13/hour12.json

    A monthly source has no data hour of its own, so it lands one file per month:

        <root>/source=<name>/year=2026/month09.json

    Every component is zero-padded so that lexicographic listing matches
    chronological order, in the local folder now and in S3 in phase 4.
    """
    base = root / f"source={source.name}" / f"year={stamp:%Y}"
    if source.granularity == "month":
        return base / f"month{stamp:%m}.json"
    return base / f"month={stamp:%m}" / f"day={stamp:%d}" / f"hour{stamp:%H}.json"


def metadata_path(payload_path: Path) -> Path:
    """Name the metadata file after the payload it describes.

    hour12.json is accompanied by hour12.metadata.json, month09.json by
    month09.metadata.json.
    """
    return payload_path.with_suffix(".metadata.json")

def build_metadata(source: Source, payload: bytes, fetched_at: datetime) -> bytes:
    """Describe one fetch.

    The payload itself cannot hold this: the bytes are stored unchanged, and the
    file name is the hour of the data, so nothing in the landing zone would
    otherwise record when the fetch happened.

    The digest lets a later fetch be compared against a stored one without reading
    the whole body, which is what makes a monthly reference fetch cheap to check
    for changes.
    """
    document = {
        "source": source.name,
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    return json.dumps(document, indent=2).encode() + b"\n"


def read_metadata(path: Path) -> dict:
    """Read the sidecar that records when a payload was fetched.

    A payload without one cannot be loaded: fetched_datetime is NOT NULL, and
    inventing a value would put a fiction in the warehouse.
    """
    document = json.loads(path.read_text())
    missing = {"source", "fetched_at", "sha256"} - set(document)
    if missing:
        raise ValueError(f"{path} is missing {sorted(missing)}")
    return document
