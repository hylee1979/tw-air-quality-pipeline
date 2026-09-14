# Schema

## Raw layer

### raw

**grain**: the payload of aqi or weather query each time

| column | type | key | note |
|---|---|---|---|
| id | bigint | PK | |
| json | jsonb | | |
| data_datetime | timestamptz | | 資料紀錄的時間 |
| fetched_datetime | timestamptz | | 我們抓取的時間 |
| source | text | | |

## Star schema

### fact_pollution_concentration

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

### fact_aqi

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

### fact_weather

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

### dim_site

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

### dim_weather_station

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

### dim_pollutant

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

### dim_aqi_level

| column | type | key | note |
|---|---|---|---|
| status_id | int | PK | |
| status | text | | |
| lower_bound | int | | |
| upper_bound | int | | |

### dim_date

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

### dim_time

| column | type | key | note |
|---|---|---|---|
| time_id | time | PK | |
| hour | int | | |
| is_daytime | bool | | |
