"""Tests for the extract step.

Only `fetch` and `main` need a session, and a small stand-in is enough: nothing
here opens a socket. The retry policy is checked by reading the configuration
off the adapter rather than by provoking real retries.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest
import requests

from aqi_pipeline import extract
from aqi_pipeline.extract import Fetched, build_session, fetch, parse_args, write_atomic
from aqi_pipeline.sources import SOURCES, TAIPEI, metadata_path, read_metadata, target_path

MOENV = SOURCES["moenv_hourly"]
CWA = SOURCES["cwa_hourly"]
STATIONS = SOURCES["moenv_stations"]


class FakeResponse:
    """The parts of a requests.Response that fetch actually touches."""

    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for url")


class FakeSession:
    """Records the call it was given and hands back a canned response."""

    def __init__(self, response: FakeResponse | Exception) -> None:
        self._response = response
        self.calls: list[dict] = []

    def get(self, url: str, params: dict, timeout: tuple) -> FakeResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    def close(self) -> None:
        pass


# --- the retry policy ------------------------------------------------------


def retry_config():
    return build_session().get_adapter("https://example.invalid").max_retries


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_statuses_are_retried(status: int) -> None:
    assert status in retry_config().status_forcelist


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_errors_are_not_retried(status: int) -> None:
    """Retrying these only delays the failure; the answer will not change."""
    assert status not in retry_config().status_forcelist


def test_backoff_grows_and_carries_jitter() -> None:
    """Without jitter, concurrent retries line up and hit the API in step."""
    config = retry_config()
    assert config.total > 0
    assert config.backoff_factor > 0
    assert config.backoff_jitter > 0


def test_only_get_is_retried() -> None:
    assert set(config := retry_config().allowed_methods) == {"GET"}, config


def test_a_retry_after_header_is_respected() -> None:
    assert retry_config().respect_retry_after_header is True


# --- write_atomic ----------------------------------------------------------


def test_write_atomic_creates_missing_directories(tmp_path: Path) -> None:
    path = tmp_path / "year=2026" / "month=09" / "hour08.json"
    write_atomic(path, b"payload")
    assert path.read_bytes() == b"payload"


def test_write_atomic_replaces_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "hour08.json"
    write_atomic(path, b"first")
    write_atomic(path, b"second")
    assert path.read_bytes() == b"second"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["hour08.json"]


def test_write_atomic_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    write_atomic(tmp_path / "hour08.json", b"payload")
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_failed_write_cleans_up_and_leaves_the_old_file_alone(tmp_path: Path) -> None:
    """A half-written file would be read by the loader as if it were complete."""
    path = tmp_path / "hour08.json"
    write_atomic(path, b"good")

    with pytest.raises(TypeError):
        write_atomic(path, "not bytes")  # type: ignore[arg-type]

    assert path.read_bytes() == b"good"
    assert list(tmp_path.glob("*.tmp")) == []


# --- the command line ------------------------------------------------------


def test_source_is_required() -> None:
    with pytest.raises(SystemExit):
        parse_args([])


def test_an_unknown_source_is_refused() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--source", "nope"])


def test_landing_root_defaults_to_the_shared_constant() -> None:
    assert parse_args(["--source", "moenv_hourly"]).landing_root == extract.LANDING_ROOT


# --- fetch -----------------------------------------------------------------


def test_fetch_returns_the_bytes_unchanged() -> None:
    body = b'{"a": 1}'
    fetched = fetch(FakeSession(FakeResponse(body)), MOENV, "secret")
    assert isinstance(fetched, Fetched)
    assert fetched.payload == body
    assert fetched.document == {"a": 1}


def test_fetch_stamps_the_moment_the_response_came_back() -> None:
    before = datetime.now(tz=TAIPEI)
    fetched = fetch(FakeSession(FakeResponse(b"[]")), MOENV, "secret")
    after = datetime.now(tz=TAIPEI)
    assert before <= fetched.fetched_at <= after


@pytest.mark.parametrize(
    "source,key_param", [(MOENV, "api_key"), (CWA, "Authorization")]
)
def test_the_key_goes_in_the_parameter_that_platform_expects(source, key_param) -> None:
    """The two platforms name it differently; sending the wrong one fails auth."""
    session = FakeSession(FakeResponse(b"[]"))
    fetch(session, source, "secret")
    assert session.calls[0]["params"][key_param] == "secret"


def test_a_limit_is_sent_so_the_platform_default_cannot_truncate() -> None:
    session = FakeSession(FakeResponse(b"[]"))
    fetch(session, MOENV, "secret")
    assert session.calls[0]["params"]["limit"] == "1000"


def test_both_timeouts_are_set() -> None:
    session = FakeSession(FakeResponse(b"[]"))
    fetch(session, MOENV, "secret")
    connect, read = session.calls[0]["timeout"]
    assert connect > 0 and read > connect


def test_an_http_error_is_raised_not_swallowed() -> None:
    with pytest.raises(requests.HTTPError):
        fetch(FakeSession(FakeResponse(b"nope", status_code=500)), MOENV, "secret")


def test_a_body_that_is_not_json_is_rejected() -> None:
    with pytest.raises(json.JSONDecodeError):
        fetch(FakeSession(FakeResponse(b"<html>error</html>")), MOENV, "secret")


def test_a_short_payload_still_succeeds() -> None:
    """Coverage is a data quality question, not an extract failure.

    Failing here would write no file, so the hour where only a few stations
    reported would leave no trace at all.
    """
    fetched = fetch(FakeSession(FakeResponse(b'[{"siteid": "1"}]')), MOENV, "secret")
    assert fetched.document == [{"siteid": "1"}]


# --- main ------------------------------------------------------------------


@pytest.fixture
def isolated_env(monkeypatch):
    """Keep the real .env and the real network out of these tests."""
    monkeypatch.setattr(extract, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("MOENV_API_KEY", raising=False)
    return monkeypatch


def run_main(monkeypatch, tmp_path: Path, source_name: str, body: bytes) -> int:
    session = FakeSession(FakeResponse(body))
    monkeypatch.setattr(extract, "build_session", lambda: session)
    return extract.main(["--source", source_name, "--landing-root", str(tmp_path)])


def test_a_missing_key_fails_before_anything_is_written(isolated_env, tmp_path: Path) -> None:
    assert run_main(isolated_env, tmp_path, "moenv_hourly", b"[]") == 1
    assert list(tmp_path.rglob("*.json")) == []


def test_a_successful_run_lands_the_payload_and_its_metadata(
    isolated_env, tmp_path: Path
) -> None:
    isolated_env.setenv("MOENV_API_KEY", "secret")
    body = b'[{"publishtime": "2026/09/11 21:00:00"}]'

    assert run_main(isolated_env, tmp_path, "moenv_hourly", body) == 0

    stamp = datetime(2026, 9, 11, 21, tzinfo=TAIPEI)
    payload_path = target_path(tmp_path, SOURCES["moenv_hourly"], stamp)
    assert payload_path.read_bytes() == body

    document = read_metadata(metadata_path(payload_path))
    assert document["source"] == "moenv_hourly"
    assert document["sha256"] == hashlib.sha256(body).hexdigest()


def test_the_file_is_filed_under_the_data_hour_not_the_clock(
    isolated_env, tmp_path: Path
) -> None:
    """A feed running hours behind must not invent an hour it did not report."""
    isolated_env.setenv("MOENV_API_KEY", "secret")
    body = b'[{"publishtime": "2026/09/11 21:00:00"}]'
    run_main(isolated_env, tmp_path, "moenv_hourly", body)
    assert (tmp_path / "source=moenv_hourly/year=2026/month=09/day=11/hour21.json").exists()


def test_the_api_key_never_reaches_the_log(isolated_env, tmp_path: Path, caplog) -> None:
    """str() of a requests error contains the URL, and the URL carries the key."""
    isolated_env.setenv("MOENV_API_KEY", "secret-key-value")
    session = FakeSession(
        requests.ConnectionError("failed for url: https://x?api_key=secret-key-value")
    )
    isolated_env.setattr(extract, "build_session", lambda: session)

    with caplog.at_level("ERROR"):
        assert extract.main(["--source", "moenv_hourly", "--landing-root", str(tmp_path)]) == 1

    assert "secret-key-value" not in caplog.text
