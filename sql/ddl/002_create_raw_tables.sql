CREATE TABLE IF NOT EXISTS raw.hourly_payload (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    data_datetime TIMESTAMPTZ NOT NULL,
    fetched_datetime TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    CONSTRAINT uq_hourly_payload_source_data_datetime UNIQUE (source, data_datetime)
);

CREATE TABLE IF NOT EXISTS raw.reference_payload (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    first_seen TIMESTAMPTZ NOT NULL,
    fetched_datetime TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    CONSTRAINT uq_reference_payload_source_sha256 UNIQUE (source, sha256)
);

COMMENT ON TABLE raw.hourly_payload IS
    'Landing table for the hourly feeds. Grain: one row per source per data hour. '
    'The payload is stored exactly as the API returned it, so every later step can be re-run from it.';
COMMENT ON COLUMN raw.hourly_payload.id IS 'Surrogate key.';
COMMENT ON COLUMN raw.hourly_payload.source IS
    'Source slug, the same one used in the landing-zone path, e.g. moenv_hourly.';
COMMENT ON COLUMN raw.hourly_payload.data_datetime IS
    'The hour the readings describe, read from the payload rather than from the clock.';
COMMENT ON COLUMN raw.hourly_payload.fetched_datetime IS
    'When the most recent fetch that wrote this row came back.';
COMMENT ON COLUMN raw.hourly_payload.payload IS 'The API response, unchanged.';

COMMENT ON TABLE raw.reference_payload IS
    'Landing table for reference data that carries no timestamp of its own. '
    'Grain: one row per distinct version, identified by the digest of the payload.';
COMMENT ON COLUMN raw.reference_payload.id IS 'Surrogate key.';
COMMENT ON COLUMN raw.reference_payload.source IS
    'Source slug, the same one used in the landing-zone path, e.g. moenv_stations.';
COMMENT ON COLUMN raw.reference_payload.sha256 IS
    'Hex digest of the payload. This is what identifies a version.';
COMMENT ON COLUMN raw.reference_payload.first_seen IS
    'When this version was first observed. Never moves once written.';
COMMENT ON COLUMN raw.reference_payload.fetched_datetime IS
    'When this version was last observed. Moved forward by every fetch that lands on the row.';
COMMENT ON COLUMN raw.reference_payload.payload IS 'The API response, unchanged.';
