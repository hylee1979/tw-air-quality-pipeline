
I use long table because it's easier to add new pollutants. We don't need to change schema.

fact_pollution_concentration
id BIGSERIAL PRIMARY KEY -> easier for engineering
UNIQUE (site_id, publishtime, target_id) -> promise the idempotancy
fact_aqi
id BIGSERIAL PRIMARY KEY -> easier for engineering
UNIQUE (site_id, publishtime) -> promise the idempotancy
fact_weather
id BIGSERIAL PRIMARY KEY -> easier for engineering
UNIQUE (station_id, publishtime) -> promise the idempotancy

use timestamptz, becasue we have different data sources, in case their time format is different.
決定在fact table 保留原始publishtime，為了audit/debugging方便，後續如果要計算時間距離等等也比較方便

the type of concentration is numeric rather than float, because we need to compare it to legal limit. we need it to be accurate. 

need other data source:
is_holiday, legal_limit

we need to find the nearest station of each aqi site beforehand, using longitude and latitude.

aqi uses TWD97 so we choose to use weather station's WGS84. their difference in at centimeter level.
data from [AQX_P_07](https://data.moenv.gov.tw/dataset/detail/AQX_P_07)

precipitation is the accumulated precipitation of that day
https://opendata.cwa.gov.tw/opendatadoc/Observation/O-A0001-001.pdf

null: 
-99 for weather station
"" for aqi data
all convert to NULL before loading

both aqi and weather data have wind speed and direction. we use the ones from aqi data because we ask questions around aqi.

avg_window the unit is hour
avg_window change to text because it's only a description for people. we don't use it to compute. 

aqi level refers to https://airtw.moenv.gov.tw/CHT/Information/Standard/AirQualityIndicator.aspx

