# Schema

## Raw layer

Two tables in the `raw` schema. They are separate because their grains differ: an hourly reading is
identified by the hour it describes, whereas the station master carries no time of its own and is
identified by its content.

### raw.hourly_payload

**grain**: one row per source per data hour

| column | type | key | note |
|---|---|---|---|
| id | bigint | PK | |
| source | text | UQ | |
| data_datetime | timestamptz | UQ | 資料紀錄的時間 |
| fetched_datetime | timestamptz | | 我們抓取的時間 |
| payload | jsonb | | the response, stored unchanged |

`UNIQUE (source, data_datetime)` is what makes the load idempotent: re-loading an hour addresses the
row already there. Both key columns are therefore NOT NULL.

This table carries no digest of the payload. One would reveal an hour whose bytes changed between two
fetches, but nothing in the project needs to answer that yet.

### raw.reference_payload

**grain**: one row per distinct version of a reference payload

| column | type | key | note |
|---|---|---|---|
| id | bigint | PK | |
| source | text | UQ | |
| sha256 | text | UQ | digest of the payload, hex |
| first_seen | timestamptz | | 第一次看到這個版本的時間 |
| fetched_datetime | timestamptz | | 最近一次看到這個版本的時間 |
| payload | jsonb | | the response, stored unchanged |

`UNIQUE (source, sha256)` means a monthly fetch that finds nothing changed collides with the stored
row, and only a real change inserts a new one. The table is therefore a version history of the
station master data, which is the raw material for giving `dim_site` slowly changing dimension
history later.

There is no `data_datetime` here. Keying on a nullable column would not work, because a UNIQUE
constraint treats NULLs as distinct from one another.

The two timestamps do different jobs. `first_seen` is written once, when a version appears, and never
moves. `fetched_datetime` is moved forward by every fetch that lands on the row, so it reads as the
last time the version was seen.

Three questions fall out of that pair: when a given version appeared, when it was last confirmed
unchanged, and, from the newest row, when the master data last changed.

## Star schema

### marts.fact_pollution_concentration

**grain**: the concentration or avg concentration of a pollutant at a site at an hour

| column | type | key | note |
|---|---|---|---|
| id | bigint | PK | |
| site_id | int | FK | |
| publishtime | timestamptz | | |
| target_id | int | FK | |
| date_id | date | FK | |
| time_id | time | FK | |
| concentration | numeric(6,2) | | not additive |

### marts.fact_aqi

**grain**: the data of a site at an hour, including aqi and wind

| column | type | key | note |
|---|---|---|---|
| id | bigint | PK | |
| site_id | int | FK | |
| publishtime | timestamptz | | |
| date_id | date | FK | |
| time_id | time | FK | |
| status_id | int | FK | |
| aqi | int | | not additive |
| main_pollutant_id | int | FK | |
| wind_speed | float | | not additive |
| wind_direc | int | | not additive |

### marts.fact_weather

**grain**: the hourly weather data of a weather station

| column | type | key | note |
|---|---|---|---|
| id | bigint | PK | |
| station_id | text | FK | |
| publishtime | timestamptz | | |
| date_id | date | FK | |
| time_id | time | FK | |
| weather | text | | |
| precipitation | float | | not additive |
| winddirection | float | | not additive |
| windspeed | float | | not additive |
| airtemperature | float | | not additive |
| relativehumidity | float | | not additive |
| airpressure | float | | not additive |

## Dimension tables

### marts.dim_site

Source: should come from [AQX_P_07](https://data.moenv.gov.tw/dataset/detail/AQX_P_07)

| column | type | key | note |
|---|---|---|---|
| site_id | int | PK | |
| sitename | text | | |
| areaname | text | | |
| county | text | | |
| township | text | | |
| siteaddress | text | | |
| longitude | float | | |
| latitude | float | | |
| sitetype | text | | |
| station_id | text | FK | the nearest station of that site |

### marts.dim_weather_station

| column | type | key | note |
|---|---|---|---|
| station_id | text | PK | |
| stationname | text | | |
| stationlongitude | float | | |
| stationlatitude | float | | |
| stationaltitude | float | | |
| countyname | text | | |
| townname | text | | |
| countycode | int | | |
| towncode | int | | |

### marts.dim_pollutant

| column | type | key | note |
|---|---|---|---|
| target_id | int | PK | |
| target_name | text | | includes pollutant and the measurement method |
| pollutant_name | text | | only the pollutant |
| unit | text | | |
| is_instant | bool | | |
| avg_window | text | | |
| legal_limit | numeric(6,2) | | not in moenv json, need other sources |

Note: here o3 and o3_8hr have different id.

### marts.dim_aqi_level

| column | type | key | note |
|---|---|---|---|
| status_id | int | PK | |
| status | text | | |
| lower_bound | int | | |
| upper_bound | int | | |

### marts.dim_date

| column | type | key | note |
|---|---|---|---|
| date_id | date | PK | |
| year | int | | |
| month | int | | |
| season | int | | |
| day | int | | |
| day_of_week | int | | |
| is_weekend | bool | | |
| is_holiday | bool | | |

### marts.dim_time

| column | type | key | note |
|---|---|---|---|
| time_id | time | PK | |
| hour | int | | |
| is_daytime | bool | | |
