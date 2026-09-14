"""Fetch one source's current payload and land it as raw JSON.

This module is the extract step. Its whole job is to obtain bytes from an API and
store them unchanged. It does not reshape fields, cast types, validate coverage or
touch the database, so that every later step can be re-run from the stored file.

Run it as:

    uv run python -m aqi_pipeline.extract --source moenv_hourly

The decisions this module implements are recorded in docs/decisionlog.md under
"Extractor".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Written to, and read back by, the loader in the next step.
LANDING_ROOT = Path("data/raw")

# Both platforms report in local time. The air-quality feed omits the offset, so
# it has to be attached; the weather feed states it.
TAIPEI = ZoneInfo("Asia/Taipei")

# Connect, then read. Separate because they fail for different reasons.
TIMEOUT = (5, 15)


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
class Fetched:
    """One successful call.

    Attributes:
        payload: The response body, byte for byte as the API sent it.
        document: The same body parsed, kept only so that the data hour can be
            read without parsing twice.
        fetched_at: The moment the response came back, read immediately after the
            request returned rather than at the end of the run.
    """

    payload: bytes
    document: Any
    fetched_at: datetime


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source",
        required=True,
        choices=sorted(SOURCES),
        help="which API to fetch; one source per run",
    )
    parser.add_argument(
        "--landing-root",
        type=Path,
        default=LANDING_ROOT,
        help=f"where raw JSON is written (default: {LANDING_ROOT})",
    )
    return parser.parse_args(argv)


def build_session() -> requests.Session:
    """Return a session that retries on its own.

    Retries cover 429 and 5xx, connect and read timeouts, and dropped
    connections. A 400, 401, 403 or 404 is not retried: the answer would be the
    same every time. Waits grow exponentially and carry jitter so that
    concurrent retries do not line up and hit the API in step.
    """
    retry = Retry(
        total=5,
        backoff_factor=1.0,
        backoff_jitter=1.0,
        backoff_max=60.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch(session: requests.Session, source: Source, api_key: str) -> Fetched:
    """Call the source once and return its body unchanged, plus what came with it.

    The bytes are what gets written to disk, so they must stay byte-identical to
    what the API sent.

    A run succeeds on a 2xx whose body parses as JSON. Coverage is not checked
    here: a short station list is a data quality question, not an extract
    failure.
    """
    params = {**source.params, source.key_param: api_key}
    response = session.get(source.url, params=params, timeout=TIMEOUT)
    fetched_at = datetime.now(tz=TAIPEI)
    response.raise_for_status()

    payload = response.content
    document = json.loads(payload)  # raises on a body that is not JSON
    logger.info(
        "fetched source=%s status=%s bytes=%d",
        source.name,
        response.status_code,
        len(payload),
    )
    return Fetched(payload=payload, document=document, fetched_at=fetched_at)


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


def build_metadata(source: Source, fetched: Fetched) -> bytes:
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
        "fetched_at": fetched.fetched_at.isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(fetched.payload).hexdigest(),
    }
    return json.dumps(document, indent=2).encode() + b"\n"


def write_atomic(path: Path, data: bytes) -> None:
    """Write bytes, replacing whatever was there before.

    The write goes to a temporary file in the same directory and is then renamed
    into place. os.replace is atomic within a filesystem, so a crash midway
    cannot leave a half-written file for the loader to read as complete.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    """Wire the steps together and return a process exit code.

    Returns 0 on success and non-zero on failure. Airflow reads the exit code in
    phase 3, so a failure that returned 0 would be recorded as a success.
    """
    args = parse_args(argv)
    source = SOURCES[args.source]

    load_dotenv()
    api_key = os.environ.get(source.key_env)
    if not api_key:
        logger.error("%s is not set; copy .env.example to .env", source.key_env)
        return 1

    session = build_session()
    try:
        fetched = fetch(session, source, api_key)
    except requests.RequestException as error:
        # str(error) can contain the full URL, and the URL carries the key.
        logger.error("fetch failed source=%s error=%s", source.name, type(error).__name__)
        return 1
    except json.JSONDecodeError as error:
        logger.error("response was not JSON source=%s error=%s", source.name, error)
        return 1
    finally:
        session.close()

    try:
        stamp = (
            source.data_time(fetched.document)
            if source.data_time
            else fetched.fetched_at
        )
    except (KeyError, TypeError, ValueError) as error:
        logger.error("could not read the data time source=%s error=%s", source.name, error)
        return 1

    # The payload goes first: it is the part that cannot be obtained again.
    path = target_path(args.landing_root, source, stamp)
    write_atomic(path, fetched.payload)
    write_atomic(metadata_path(path), build_metadata(source, fetched))
    logger.info(
        "landed source=%s data_time=%s path=%s",
        source.name,
        stamp.isoformat(timespec="seconds"),
        path,
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    sys.exit(main())
