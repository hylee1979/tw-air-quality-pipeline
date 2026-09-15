CREATE TABLE IF NOT EXISTS marts.dim_weather_station (
    station_id TEXT PRIMARY KEY,
    stationname TEXT NOT NULL,
    stationlongitude FLOAT,
    stationlatitude FLOAT,
    stationaltitude FLOAT,
    countyname TEXT,
    townname TEXT,
    countycode INT,
    towncode INT
);

CREATE TABLE IF NOT EXISTS marts.dim_site (
    site_id INT PRIMARY KEY,
    sitename TEXT NOT NULL,
    areaname TEXT,
    county TEXT,
    township TEXT,
    siteaddress TEXT,
    longitude FLOAT,
    latitude FLOAT,
    sitetype TEXT,
    station_id TEXT REFERENCES marts.dim_weather_station(station_id)
);

CREATE TABLE IF NOT EXISTS marts.dim_pollutant (
    target_id INT PRIMARY KEY,
    target_name TEXT NOT NULL,
    pollutant_name TEXT NOT NULL,
    unit TEXT,
    is_instant BOOL,
    avg_window TEXT,
    legal_limit NUMERIC(6,2)
);

CREATE TABLE IF NOT EXISTS marts.dim_aqi_level (
    status_id INT PRIMARY KEY,
    status TEXT NOT NULL,
    lower_bound INT,
    upper_bound INT
);

CREATE TABLE IF NOT EXISTS marts.dim_date (
    date_id DATE PRIMARY KEY,
    year INT NOT NULL,
    month INT NOT NULL,
    season INT NOT NULL,
    day INT NOT NULL,
    day_of_week INT NOT NULL,
    is_weekend BOOL NOT NULL,
    is_holiday BOOL
);

CREATE TABLE IF NOT EXISTS marts.dim_time (
    time_id TIME PRIMARY KEY,
    hour INT NOT NULL,
    is_daytime BOOL NOT NULL
);

CREATE TABLE IF NOT EXISTS marts.fact_pollution_concentration (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    site_id INT REFERENCES marts.dim_site(site_id) NOT NULL,
    publishtime TIMESTAMPTZ NOT NULL,
    target_id INT REFERENCES marts.dim_pollutant(target_id) NOT NULL,
    date_id DATE REFERENCES marts.dim_date(date_id) NOT NULL,
    time_id TIME REFERENCES marts.dim_time(time_id) NOT NULL,
    concentration NUMERIC(6,2),
    CONSTRAINT uq_fact_pollution_site_hour_target UNIQUE (site_id, publishtime, target_id)
);

CREATE TABLE IF NOT EXISTS marts.fact_aqi (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    site_id INT REFERENCES marts.dim_site(site_id) NOT NULL,
    publishtime TIMESTAMPTZ NOT NULL,
    date_id DATE REFERENCES marts.dim_date(date_id) NOT NULL,
    time_id TIME REFERENCES marts.dim_time(time_id) NOT NULL,
    status_id INT REFERENCES marts.dim_aqi_level(status_id),
    aqi INT,
    main_pollutant_id INT REFERENCES marts.dim_pollutant(target_id),
    wind_speed FLOAT,
    wind_direc INT, 
    CONSTRAINT uq_fact_aqi_site_hour UNIQUE (site_id, publishtime)
);

CREATE TABLE IF NOT EXISTS marts.fact_weather (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    station_id TEXT REFERENCES marts.dim_weather_station(station_id) NOT NULL,
    publishtime TIMESTAMPTZ NOT NULL,
    date_id DATE REFERENCES marts.dim_date(date_id) NOT NULL,
    time_id TIME REFERENCES marts.dim_time(time_id) NOT NULL,
    weather TEXT,
    precipitation FLOAT,
    winddirection FLOAT,
    windspeed FLOAT,
    airtemperature FLOAT,
    relativehumidity FLOAT,
    airpressure FLOAT,
    CONSTRAINT uq_fact_weather_station_hour UNIQUE (station_id, publishtime)
);


COMMENT ON TABLE marts.dim_weather_station IS
    'One row per automatic weather station reported by the Central Weather Administration. '
    'Coordinates are WGS84, which is within centimetres of the TWD97 the air quality platform uses.';
COMMENT ON COLUMN marts.dim_weather_station.station_id IS
    'The platform''s own station code, e.g. C0TB40. Text, not a number.';
COMMENT ON COLUMN marts.dim_weather_station.stationaltitude IS 'Metres above sea level.';

COMMENT ON TABLE marts.dim_site IS
    'One row per air quality monitoring site. Built from the station master data AQX_P_07, '
    'topped up from the hourly feed for sites the master does not list.';
COMMENT ON COLUMN marts.dim_site.site_id IS 'The platform''s own site number, used as the key.';
COMMENT ON COLUMN marts.dim_site.longitude IS 'TWD97, as published in AQX_P_07.';
COMMENT ON COLUMN marts.dim_site.latitude IS 'TWD97, as published in AQX_P_07.';
COMMENT ON COLUMN marts.dim_site.station_id IS
    'The nearest weather station, worked out once from the coordinates.';
COMMENT ON COLUMN marts.dim_site.areaname IS
    'Air quality region. Only in the master data, so NULL for an inferred site.';
COMMENT ON COLUMN marts.dim_site.sitetype IS
    'General, industrial, traffic and so on. Only in the master data, so NULL for an inferred site.';

COMMENT ON TABLE marts.dim_pollutant IS
    'One row per measured quantity, not per substance: ozone measured hourly and ozone averaged '
    'over eight hours are two rows, because the legal limit is set per averaging period.';
COMMENT ON COLUMN marts.dim_pollutant.target_name IS
    'The quantity, including how it is measured, e.g. o3_8hr.';
COMMENT ON COLUMN marts.dim_pollutant.pollutant_name IS 'The substance alone, e.g. o3.';
COMMENT ON COLUMN marts.dim_pollutant.is_instant IS
    'True for an hourly reading, false for one averaged over a window.';
COMMENT ON COLUMN marts.dim_pollutant.avg_window IS
    'How the average is taken, in words. PM2.5 and PM10 are weighted across two windows, '
    'so a single number cannot describe them. Text, because nothing computes with it.';
COMMENT ON COLUMN marts.dim_pollutant.legal_limit IS
    'Statutory limit for this quantity. Not published in the hourly feed; sourced separately.';

COMMENT ON TABLE marts.dim_aqi_level IS
    'The six statutory AQI bands. See the air quality index page on the ministry''s monitoring site.';
COMMENT ON COLUMN marts.dim_aqi_level.lower_bound IS 'Inclusive.';
COMMENT ON COLUMN marts.dim_aqi_level.upper_bound IS 'Inclusive.';

COMMENT ON TABLE marts.dim_date IS 'One row per calendar day.';
COMMENT ON COLUMN marts.dim_date.season IS '1 spring, 2 summer, 3 autumn, 4 winter.';
COMMENT ON COLUMN marts.dim_date.day_of_week IS 'ISO numbering: 1 Monday through 7 Sunday.';
COMMENT ON COLUMN marts.dim_date.is_holiday IS
    'NULL until a public holiday calendar is loaded. NULL means unknown, not a working day.';

COMMENT ON TABLE marts.dim_time IS 'One row per hour of the day, so twenty-four rows.';

COMMENT ON TABLE marts.fact_pollution_concentration IS
    'Grain: one row per site, per hour, per measured quantity. Concentrations are not additive: '
    'summing them across sites or hours means nothing, so aggregates take an average.';
COMMENT ON COLUMN marts.fact_pollution_concentration.publishtime IS
    'The hour the reading describes, kept alongside the date and time keys for auditing and for '
    'arithmetic on time.';
COMMENT ON COLUMN marts.fact_pollution_concentration.concentration IS
    'The measured value, in the unit named on dim_pollutant. Not additive.';

COMMENT ON TABLE marts.fact_aqi IS
    'Grain: one row per site per hour, holding the figures that describe the whole site rather '
    'than a single pollutant.';
COMMENT ON COLUMN marts.fact_aqi.aqi IS
    'The index itself, the largest of the sub-indices. Not additive.';
COMMENT ON COLUMN marts.fact_aqi.main_pollutant_id IS
    'The quantity that produced the largest sub-index. NULL when the feed names none.';
COMMENT ON COLUMN marts.fact_aqi.wind_direc IS
    'Degrees clockwise from north. Not additive, and averaging it needs circular arithmetic.';
COMMENT ON COLUMN marts.fact_aqi.wind_speed IS 'From the air quality feed, not the weather feed.';

COMMENT ON TABLE marts.fact_weather IS
    'Grain: one row per weather station per hour. Weather stations are a different and much '
    'larger set than air quality sites, which is why this is its own table.';
COMMENT ON COLUMN marts.fact_weather.precipitation IS
    'Rainfall accumulated since midnight, not the hour''s own total, so it is not additive. '
    'An hourly figure is the difference between consecutive hours.';
COMMENT ON COLUMN marts.fact_weather.winddirection IS 'Degrees clockwise from north.';
