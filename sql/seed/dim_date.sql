-- One row per calendar day.
--
-- Generated rather than derived: a date exists whether or not any reading has
-- arrived for it, so this does not read from raw. The range is wider than the
-- data on purpose, because a fact row cannot be inserted for a date this table
-- does not carry.
--
-- generate_series over two dates returns timestamptz, not date, so the result
-- is cast once here. Without the cast the value would be converted using the
-- server's own timezone, which is UTC in the container and need not be the same
-- on RDS in phase 4.

INSERT INTO marts.dim_date (date_id, year, month, season, day, day_of_week, is_weekend, is_holiday)
WITH days AS (
    SELECT generate_series('2025-01-01'::date, '2027-12-31'::date, '1 day'::interval)::date AS d
)
SELECT
    d AS date_id,
    EXTRACT(YEAR FROM d) AS year,
    EXTRACT(MONTH FROM d) AS month,
    -- Meteorological seasons, three whole months each, which is the convention
    -- used for air quality reporting. Not the astronomical seasons, and not
    -- Taiwan's felt seasons, where autumn arrives far later than September.
    CASE
        WHEN EXTRACT(MONTH FROM d) IN (3, 4, 5) THEN 1
        WHEN EXTRACT(MONTH FROM d) IN (6, 7, 8) THEN 2
        WHEN EXTRACT(MONTH FROM d) IN (9, 10, 11) THEN 3
        ELSE 4
    END AS season,
    EXTRACT(DAY FROM d) AS day,
    -- ISODOW, so Monday is 1 and Sunday is 7, matching the column comment.
    -- Plain DOW would number Sunday 0 and quietly disagree with it.
    EXTRACT(ISODOW FROM d) AS day_of_week,
    CASE WHEN EXTRACT(ISODOW FROM d) IN (6, 7) THEN TRUE ELSE FALSE END AS is_weekend,
    -- Left unknown here. Public holidays come from the government office
    -- calendar, a separate annual source, and NULL means "not yet loaded"
    -- rather than "a working day".
    NULL AS is_holiday
FROM days
ON CONFLICT (date_id) DO UPDATE
-- Two different reasons for a column to be absent from this list.
--
-- year, month and day are omitted because they cannot change: they are
-- date_id read back out, so a repeat run would rewrite identical values.
--
-- is_holiday is omitted because this file must not own it. It is filled from
-- the holiday calendar, and including it here would reset every loaded holiday
-- to NULL on the next run.
SET season = EXCLUDED.season,
    day_of_week = EXCLUDED.day_of_week,
    is_weekend = EXCLUDED.is_weekend;
