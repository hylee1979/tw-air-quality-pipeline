# Decision log

## Fact table shape

I use long table because it's easier to add new pollutants. We don't need to change schema.

## Keys and idempotency

Every fact table gets a `BIGSERIAL` surrogate key, because it's easier for engineering.
Uniqueness is enforced by a `UNIQUE` constraint on the natural key, which promises the idempotency.

| table | primary key | unique constraint |
|---|---|---|
| fact_pollution_concentration | id BIGSERIAL | (site_id, publishtime, target_id) |
| fact_aqi | id BIGSERIAL | (site_id, publishtime) |
| fact_weather | id BIGSERIAL | (station_id, publishtime) |

## Time handling

Use `timestamptz`, because we have different data sources, in case their time format is different.

決定在 fact table 保留原始 publishtime，為了 audit 和 debugging 方便。後續如果要計算時間距離等等也比較方便。

## Data types

The type of concentration is `numeric` rather than `float`, because we need to compare it to legal limit. We need it to be accurate.

## External data needed

These columns are not in the source APIs and need another data source:

- `is_holiday`
- `legal_limit`

## Nearest weather station

We need to find the nearest station of each aqi site beforehand, using longitude and latitude.

## Coordinate system

aqi uses TWD97, so we choose to use weather station's WGS84. Their difference is at centimeter level.

Source: [AQX_P_07](https://data.moenv.gov.tw/dataset/detail/AQX_P_07)

## Precipitation

precipitation is the accumulated precipitation of that day.

Source: [O-A0001-001 doc (PDF)](https://opendata.cwa.gov.tw/opendatadoc/Observation/O-A0001-001.pdf)

## Null handling

Each source marks missing values differently. All of them convert to `NULL` before loading.

| source | missing value |
|---|---|
| weather station | `-99` |
| aqi data | `""` |

## Wind data source

Both aqi and weather data have wind speed and direction. We use the ones from aqi data, because we ask questions around aqi.

## avg_window

The unit is hour.

`avg_window` changed to `text`, because it's only a description for people. We don't use it to compute.

## AQI levels

aqi level refers to [空氣品質指標｜環境部](https://airtw.moenv.gov.tw/CHT/Information/Standard/AirQualityIndicator.aspx)

## Extractor

### One source per run

The extractor is one module that takes the source as a parameter, so a single run handles a single
source. This removes the question of what a run should report when two of three sources succeed and
one fails: there is never more than one source in flight.

### Landing zone layout

Raw responses are written to a Hive-style partitioned path:

```
data/raw/source=<name>/year=2026/month=09/day=12/hour<HH>.json
```

Month and day are zero-padded. Object stores list keys in lexicographic order, so `month=9` would
sort after `month=10`; the same layout moves to S3 unchanged in phase 4.

The file name is derived from the hour of the **data**, not the hour of the pull, so re-running an
hour lands on the same file. Naming by pull time instead would leave a new file behind on every run,
which would make the overwrite rule below meaningless and would break re-runs during backfill.

### Re-running the same hour

A repeated run overwrites the existing file.

This is deliberate, and it gives something up: if the API answers differently on the second call,
the first answer is gone, and `data/` is local, gitignored and not backed up. The trade accepted
here is simplicity, on the grounds that the newest response is the one worth keeping.

### Why the JSON is kept as well as loaded into the database

Extract writes files; a separate step loads them into PostgreSQL. Both layers exist on purpose.

The strongest reason is decoupling. If the extractor wrote straight to the database, then an hour of
database downtime would be an hour of data lost forever, because each API only serves the current
hour. With a file landing zone, the JSON still lands while the database is down, and the load can
catch up afterwards.

Two further reasons: object storage is far cheaper than database storage for years of archive, and
the whole warehouse can be dropped and rebuilt from the files without calling the APIs again.

### Retry policy

Retry on HTTP 429 and 5xx, on read and connect timeouts, and on dropped connections.

Do not retry on 400, 401, 403 or 404. The response will be the same every time, so retrying only
delays the failure.

Waits grow exponentially and carry jitter, so that concurrent retries do not line up and hit the API
in step.

### Timeouts

Five seconds to establish the connection, fifteen seconds to read the response.

The two are set separately because they fail for different reasons. A connection that will not
establish usually means a dead host or a DNS problem, and waiting longer rarely helps. A slow read,
by contrast, is normal for a large body: the weather response is about 1.6 MB against roughly 45 KB
for air quality.

Retries multiply these figures. The worst case for one run is the read timeout times the number of
attempts, plus the backoff waits, so any task timeout set in Airflow in phase 3 has to exceed that.

### What counts as a failure

A run succeeds if it receives a 2xx response whose body parses as JSON. Nothing else is checked at
this layer.

An earlier draft of this decision also failed a run when the response held fewer than the expected
number of stations, 84 for air quality and 876 for weather. That was moved to the data quality tests
for two reasons. It discarded the evidence: a run that fails writes no file, so the hour where only
60 stations reported would leave no trace, and that is exactly the hour worth investigating. And the
expected count is not stable, so a newly commissioned station would fail every run until the number
was edited by hand. Station coverage is a data quality question, not an extraction failure.

### Cadence of static sources

The air quality station master data, AQX_P_07, is effectively static and does not need the hourly
cadence of the readings.

It gets its own schedule, pulled monthly, which in phase 3 means a second DAG rather than an extra
task on the hourly one. How often a source is pulled follows from how fast it changes, not from the
cadence of the facts it describes.

This source lands at `year=<YYYY>/month<MM>.json`, which holds one snapshot per month: a second
pull inside the same month replaces the first. That still gives a month-by-month history of the
station master data for free, even while `dim_site` itself keeps no history. Preserving every
individual pull would mean putting the pull date in the file name as well.
