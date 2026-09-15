"""Load landed JSON into the raw schema.

This module is the load step. It reads files the extractor already wrote and
inserts them into PostgreSQL, one file per transaction, so that a failure part
way through a range leaves the successes committed.

Run it as:

    uv run python -m aqi_pipeline.load --source moenv_hourly --hour 2026-09-11T21
    uv run python -m aqi_pipeline.load --source cwa_hourly --from 2026-09-01 --to 2026-09-02
    uv run python -m aqi_pipeline.load --source moenv_stations --month 2026-09

The decisions this module implements are recorded in docs/decisionlog.md under
"Raw layer" and "Loader".
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from aqi_pipeline.sources import (
    LANDING_ROOT,
    SOURCES,
    TAIPEI,
    Source,
    metadata_path,
    read_metadata,
    target_path,
)

logger = logging.getLogger(__name__)

DEFAULT_FAILED_FILE = Path("failed.txt")

# The named constraints come from sql/002_create_raw_tables.sql. Naming them
# means the conflict target reads as an intention rather than a column list.
INSERT_HOURLY = """
    INSERT INTO raw.hourly_payload (source, data_datetime, fetched_datetime, payload)
    VALUES (%s, %s, %s, %s::jsonb)
    ON CONFLICT ON CONSTRAINT uq_hourly_payload_source_data_datetime DO UPDATE
    SET payload = EXCLUDED.payload,
        fetched_datetime = EXCLUDED.fetched_datetime
"""

# first_seen is deliberately absent from the update: it records when a version
# first appeared and must not move when the same version is seen again.
INSERT_REFERENCE = """
    INSERT INTO raw.reference_payload (source, sha256, first_seen, fetched_datetime, payload)
    VALUES (%s, %s, %s, %s, %s::jsonb)
    ON CONFLICT ON CONSTRAINT uq_reference_payload_source_sha256 DO UPDATE
    SET fetched_datetime = EXCLUDED.fetched_datetime
"""


def parse_period(source: Source, text: str) -> datetime:
    """Read one period off the command line.

    An hourly source is named to the hour, "2026-09-11T21". A monthly source is
    named to the month, "2026-09". Both are read as Taipei local time, which is
    what the landing-zone path is built from.
    """
    if source.granularity == "month":
        return datetime.strptime(text, "%Y-%m").replace(tzinfo=TAIPEI)
    return datetime.fromisoformat(text).replace(tzinfo=TAIPEI)


def format_period(source: Source, stamp: datetime) -> str:
    """Write a period back in the form parse_period accepts.

    This is what the failure file holds, so that a failed run can be retried by
    feeding the file straight back to --hour or --month.
    """
    if source.granularity == "month":
        return f"{stamp:%Y-%m}"
    return f"{stamp:%Y-%m-%dT%H}"


def periods_from_args(source: Source, args: argparse.Namespace) -> list[datetime]:
    """Work out which periods this run covers.

    Either an explicit list, which is the routine load and the retry, or a range,
    which is the backfill. A range is inclusive at both ends and steps by the
    source's own granularity.
    """
    if args.period:
        return [parse_period(source, text) for text in args.period]

    start = parse_period(source, args.start)
    end = parse_period(source, args.end)
    if end < start:
        raise ValueError(f"--to {args.end} is before --from {args.start}")

    stamps: list[datetime] = []
    current = start
    while current <= end:
        stamps.append(current)
        if source.granularity == "month":
            current = (current.replace(day=1) + timedelta(days=32)).replace(day=1)
        else:
            current += timedelta(hours=1)
    return stamps


def load_one(conn: psycopg.Connection, source: Source, stamp: datetime, root: Path) -> None:
    """Load a single period. Raises if anything about it is not right.

    The payload is passed to PostgreSQL as text and cast there, so this never
    parses the body in Python. data_datetime comes from the path rather than
    from the payload, because the path is how the whole system addresses a file.
    """
    payload_path = target_path(root, source, stamp)
    if not payload_path.exists():
        raise FileNotFoundError(payload_path)

    metadata = read_metadata(metadata_path(payload_path))
    fetched_at = datetime.fromisoformat(metadata["fetched_at"])
    payload = payload_path.read_text()

    if source.granularity == "month":
        conn.execute(
            INSERT_REFERENCE,
            (source.name, metadata["sha256"], fetched_at, fetched_at, payload),
        )
    else:
        conn.execute(INSERT_HOURLY, (source.name, stamp, fetched_at, payload))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Read the command line.

    --hour and --month are the same argument under two names, so that the flag
    matches the shape of the source being asked for.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, choices=sorted(SOURCES))
    parser.add_argument(
        "--hour",
        "--month",
        dest="period",
        nargs="+",
        metavar="PERIOD",
        help='periods to load, e.g. 2026-09-11T21, or 2026-09 for a monthly source',
    )
    parser.add_argument("--from", dest="start", metavar="PERIOD", help="start of a range, inclusive")
    parser.add_argument("--to", dest="end", metavar="PERIOD", help="end of a range, inclusive")
    parser.add_argument("--landing-root", type=Path, default=LANDING_ROOT)
    parser.add_argument(
        "--failed-file",
        type=Path,
        default=DEFAULT_FAILED_FILE,
        help=f"where the periods that failed are written (default: {DEFAULT_FAILED_FILE})",
    )
    args = parser.parse_args(argv)

    if bool(args.period) == bool(args.start or args.end):
        parser.error("give either --hour/--month, or --from and --to")
    if not args.period and not (args.start and args.end):
        parser.error("a range needs both --from and --to")
    return args


def main(argv: list[str] | None = None) -> int:
    """Load every period asked for and report which ones did not land.

    Each period is its own transaction, so one bad file does not undo the ones
    already committed. The failures are written to a file in the form the
    command line accepts, so that a retry is the same command with that file.
    """
    args = parse_args(argv)
    source = SOURCES[args.source]

    try:
        periods = periods_from_args(source, args)
    except ValueError as error:
        logger.error("%s", error)
        return 2

    load_dotenv()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        logger.error("DATABASE_URL is not set; copy .env.example to .env")
        return 2

    # Truncated up front so that a crash cannot leave yesterday's failures behind.
    args.failed_file.write_text("")

    failures: list[datetime] = []
    with psycopg.connect(dsn) as conn:
        for stamp in periods:
            label = format_period(source, stamp)
            try:
                with conn.transaction():
                    load_one(conn, source, stamp, args.landing_root)
            except Exception as error:
                logger.error("failed period=%s %s: %s", label, type(error).__name__, error)
                failures.append(stamp)
            else:
                logger.info("loaded source=%s period=%s", source.name, label)

    if failures:
        args.failed_file.write_text(
            "\n".join(format_period(source, stamp) for stamp in failures) + "\n"
        )
        logger.error(
            "%d of %d periods failed; retry with --%s $(cat %s)",
            len(failures),
            len(periods),
            "month" if source.granularity == "month" else "hour",
            args.failed_file,
        )
        return 1

    logger.info("loaded %d periods with no failures", len(periods))
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    sys.exit(main())
