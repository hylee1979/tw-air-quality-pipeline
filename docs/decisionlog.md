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
