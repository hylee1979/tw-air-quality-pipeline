-- One row per hour of the day, twenty-four in all.
--
-- Generated rather than derived: the hours exist whether or not any reading
-- has arrived for them, so this does not read from raw.
--
-- Re-runnable. Every column is a function of time_id, so a repeat run simply
-- rewrites the same values.

INSERT INTO marts.dim_time (time_id, hour, is_daytime)
SELECT
    make_time(h, 0, 0) AS time_id,
    h AS hour,
    -- A judgement, not a fact. Taiwan's civil twilight sits between roughly
    -- 05:30 and 18:30 across the year, so 06:00 to 18:00 inclusive is daylight
    -- for every month without needing a per-date sunrise table.
    CASE WHEN h BETWEEN 6 AND 18 THEN TRUE ELSE FALSE END AS is_daytime
FROM generate_series(0, 23) AS h
ON CONFLICT (time_id) DO UPDATE
-- hour is omitted because it cannot change: it is time_id read back out.
SET is_daytime = EXCLUDED.is_daytime;
