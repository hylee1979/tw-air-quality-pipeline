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
import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from aqi_pipeline.sources import (
    LANDING_ROOT,
    SOURCES,
    TAIPEI,
    Source,
    build_metadata,
    metadata_path,
    target_path,
)

logger = logging.getLogger(__name__)

# Connect, then read. Separate because they fail for different reasons.
TIMEOUT = (5, 15)


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
    write_atomic(metadata_path(path), build_metadata(source, fetched.payload, fetched.fetched_at))
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
