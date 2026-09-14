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

## Source behaviour

### Staleness of the air quality feed

Found while implementing `extract.py`: the hourly air quality feed was not current. Its latest
`publishtime` was 2026-09-11 21:00 while the clock read 2026-09-13 12:22, around 39 hours behind.
The weather feed was current at the same moment.

This is the source, not the pipeline. The platform's own dataset page reported the same last-updated
time, 2026-09-11 21:15:03.

Two things follow. The landing zone behaves correctly under it, because a file is named by the hour
of the data, so a stale feed rewrites one file rather than inventing new hours. And the freshness
threshold cannot be taken from the platform's nominal hourly cadence: a two-hour threshold would
alert continuously. The real distribution of gaps has to come from the historical dataset once it is
backfilled, so that the threshold reflects what the source does rather than what it promises.

### Stations missing from the master data

The hourly feed reports 84 stations. The station master, AQX_P_07, lists 80. Four stations appear
only in the hourly feed:

| siteid | name |
|---|---|
| 203 | 南投（鹿谷） |
| 204 | 屏東（琉球） |
| 311 | 新北（樹林） |
| 313 | 屏東（枋山） |

A `dim_site` built from the master alone would therefore have no row for four of the sites the fact
tables reference.

Those sites are stored anyway. The hourly feed itself carries `sitename`, `county` and the
coordinates, so those fields are populated from it, and only the fields the master alone provides
are left NULL: `areaname`, `township`, `siteaddress`, `sitetype` and `siteengname`. The questions
this project answers need the basic station attributes, not the full master record.

Kimball calls a dimension row created this way an inferred member. The fact arrived before the
dimension, so a partial row is written rather than dropping the fact or letting the foreign key
fail.

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

This is the shape for the hourly feeds. The timestamp in it is the hour of the **data**, not the hour
of the fetch, so re-running an hour lands on the same file. Naming them by fetch time instead would
leave a new file behind on every run, which would make the overwrite rule below meaningless and would
break re-runs during backfill.

The station master uses a shorter path and is timestamped by the fetch. Both differences are explained
under "Cadence of static sources".

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

It gets its own schedule, fetched monthly, which in phase 3 means a second DAG rather than an extra
task on the hourly one. How often a source is fetched follows from how fast it changes, not from the
cadence of the facts it describes.

This source lands one file per month, `year=2026/month09.json`, with the month taken from the fetch
time because the payload carries no time of its own. A second fetch inside the same month replaces the
first; across months each fetch is kept, so the file layer holds a month-by-month history.

Going finer than the month would buy nothing here. The version history that matters is in the raw
reference table, which keys on the digest and therefore records every distinct version of the master
data however often it is fetched.

### Recording the fetch time

The raw table carries a `fetched_datetime`, but nothing produced so far holds one. The file name is the
hour of the data, and the bytes are stored exactly as the API sent them.

The extractor therefore writes a small metadata file alongside each payload, recording the moment
the response came back, read immediately after the request returns rather than at the end of the
run.

The metadata file sits beside the payload and is named after it, `hour<HH>.metadata.json`. It
records the fetch time, the SHA-256 of the payload, and the source.

The digest is there so that a later fetch can be compared against a stored one without reading the
whole body. That matters most for the station master data, where the point of fetching monthly is to
find out whether anything changed at all.

The metadata file is named after the payload it describes, so it follows whatever shape that payload
uses: `hour<HH>.metadata.json` beside an hourly file, `month<MM>.metadata.json` beside the station
master.

Still to fix: the HTTP status and the byte count are also worth keeping, since those are the first
things to look at when an hour looks wrong. The URL is not, because it carries the key.

## Raw layer

### Grain and uniqueness

The hourly readings and the reference data go into separate tables in the `raw` schema, for the same
reason that `fact_aqi` and `fact_weather` are separate: their grains differ.

For the hourly payloads the grain is one row per source per data hour, and uniqueness is
`(source, data_datetime)`. Loading the same hour twice addresses the same row, and that is what makes
the load idempotent.

The station master payload carries no timestamp of its own, so there is no data hour to key on. Its
identity is its content instead: the grain is one row per distinct version, and uniqueness is
`(source, sha256)`. A monthly fetch that finds nothing changed collides with the row already stored; a
fetch that finds a change inserts a new one. The digest is stored as `text`, in hex, because nothing
compares it inside SQL.

The hourly table carries no digest. One would reveal an hour whose bytes changed between two fetches,
but nothing in the project needs to answer that yet, and the file layer has already given that
evidence up by overwriting.

Keying on the digest rather than on the fetch time has a useful side effect. The table becomes a
version history of the station master data, which is the raw material for giving `dim_site` slowly
changing dimension history later on.

An earlier draft put both kinds of payload in one table with a nullable `data_datetime`. That does
not work. A UNIQUE constraint treats NULLs as distinct from one another, so nothing would stop
unlimited duplicate rows for the source whose key is NULL. PostgreSQL 15 can override this with
`UNIQUE NULLS NOT DISTINCT`, but resting a key constraint on that detail is not worth it when the
grains differ anyway.

### Conflict behaviour

For the hourly table, on conflict update: the newer payload replaces the stored one.

This follows the landing zone, where a repeated fetch overwrites the file. Both layers therefore hold
the most recent answer for a given hour, not a history of answers for it.

For the reference table a conflict means the digest already exists, so the stored payload is
byte-identical to the incoming one and the payload itself has nothing to replace. The conflict still
does work, though: it moves `fetched_datetime` forward, leaving `first_seen` alone.

So the reference table keeps two timestamps for a reason. `first_seen` says when a version appeared
and never moves; `fetched_datetime` says when it was last seen. Between them, and with the newest row
giving the date of the last real change, the table answers when the master data changed and when it
was last confirmed not to have.

### Database schemas

Two schemas in PostgreSQL: `raw` for the landing tables and `marts` for the star schema. Table names
are written with the schema throughout `docs/schema.md`, so that the DDL and the documentation agree
on where each table lives.

A schema is a namespace. Separating the two now gives a natural boundary for the roles and grants
later in phase 1, where a reader can be granted `marts` without being granted `raw`.

## Loader

### Selecting what to load

The loader takes the source and the period as arguments and loads only what it was asked for. It
does not scan the landing zone looking for files it has not seen.

This makes a re-run or a backfill a matter of passing a different period, and it maps directly onto
an Airflow task, which always knows the interval it is running for.

It does not, by itself, guarantee that every file in the landing zone has reached the database:
nothing notices a period that was never requested. That needs a separate reconciliation check,
comparing the files present against the rows in `raw`. Still to decide: whether it runs as its own
step or as one of the data quality tests.

### Partial failure

When a run covers several periods and one of them fails, the successful ones stay committed and only
the failures are re-run. The transaction boundary is one file, not the whole batch.

Two things follow. The process must still exit non-zero when any file failed, or the caller has no
reason to retry. And it must name the periods that failed, or the caller has no way to know what to
retry.

