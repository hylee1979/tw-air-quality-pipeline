# Portfolio project plan: closing the data engineer gaps

Written 2026-09-05 for Hsin-Yu Lee. Purpose: one self-directed project that turns the four gaps
in `fact_sheet.md` (cloud, ETL or orchestration tool, SQL on a real RDBMS, DBMS operation) into
claimable, interview-ready experience for data engineer roles in Taiwan, with Australian roles as
a secondary target.

## 0. Working agreement with the AI agent in this repo

Hsin-Yu is using this project to learn the tools by hand. The agent's role is to explain, point to
documentation, review what she wrote, and answer questions. The agent does not scaffold the repo,
write project files, generate code, or run setup commands unless she explicitly asks for that
specific thing in that message. When she asks how to do something, answer with the steps and the
reasoning and let her type them. When reviewing, point at the problem and why it matters; do not
rewrite the file. Prefer teaching the underlying concept (why an idempotent upsert, why this grain)
over handing over a snippet. Read the rest of this file before answering anything about the project.

## 1. Evidence: what the saved JDs actually ask

Source: the 29 JDs saved under `job hunting 2026/positions/` (July to September 2026). Counts are
the number of JD files mentioning the term.

| Requirement | JDs mentioning | Current status in fact sheet |
|---|---|---|
| SQL | 20 | Listed, but only SQLite used in production |
| Data quality, validation, monitoring | 9 | Corning alert emails in Python; no framework, no tests |
| Cloud: AWS / Azure / GCP | 6 / 6 / 3 | DigitalOcean VPS and Melbourne Research Cloud only |
| PostgreSQL / SQL Server / MySQL | 5 / 3 / 1 | None |
| Data warehouse, data lake, data modelling | 3 + 2, plus every Taiwan DE JD | None |
| CI/CD | 4 | None |
| Orchestration: Airflow, Trinity, Pentaho, NiFi, Prefect | 2, plus Taiwan enterprise tools | systemd timers, hand-rolled |
| dbt / Snowflake / BigQuery | 2 / 1 / 1 | On the never-claim list |

Taiwan data engineer JDs specifically (Huaao, Softleader, TWM, Micron): every one asks for SQL plus
a named relational database, ETL or ELT development, and data modelling. Huaao also asks for a data
dictionary, metadata, quality monitoring, alerting, and observability. Micron asks for batch plus
streaming, data governance, technology selection, and documentation.

## 2. Priority

1. **SQL on PostgreSQL, plus dimensional modelling and basic DBMS operation.** Highest frequency,
   lowest cost, and every later phase sits on top of it.
2. **Orchestration and transformation: Apache Airflow plus dbt Core.** Moves two tools off the
   never-claim list. Airflow maps directly onto the systemd-timer work at Dysrupt.
3. **Cloud: AWS.** One cloud done concretely (S3, RDS, EC2, IAM, CloudWatch) beats three clouds
   done shallowly.
4. **Stretch, only after 1 to 3 are on the CV:** Snowflake trial as a second dbt target, a small
   streaming feed, Terraform.

## 3. Why these systems

- **PostgreSQL** over MySQL or SQL Server: free, runs in Docker on the Mac, and named in the
  Huaao, TWM, Softleader, and Claviate JDs. SQL Server and Teradata skills transfer from it.
  Snowflake and BigQuery differ more, but dbt hides most of the difference.
- **Airflow** over Trinity, Pentaho, Informatica, NiFi: those are commercial or in-house tools that
  cannot be learned meaningfully at home. Airflow is the open-source default that interviewers
  accept as the transferable equivalent, and Softleader and REA list it by name.
- **dbt Core** for transformations: it is SQL plus Jinja plus YAML, and Jinja2 is already on the
  fact sheet. It gives tests, docs, lineage, and a data dictionary almost for free, which answers
  the Huaao and Micron governance bullets.
- **AWS** over Azure or GCP: tied with Azure for mentions in the saved JDs, the dominant cloud in
  Taiwan, and its primitives map onto the DigitalOcean mental model: a VM, an object store, a
  managed Postgres. If the target shifts back to Australian Microsoft shops such as Liberty or
  Macquarie Technology, swap phase 4 to Azure with the same design.
- **Metabase** for the dashboard: Power BI Desktop does not run on macOS, and the dashboard is the
  least important layer. Metabase in Docker connects to Postgres in an afternoon.

## 4. The project: Taiwan air-quality and weather telemetry platform

**One-line pitch.** An hourly pipeline that ingests Taiwan's public air-quality and weather station
readings, lands raw JSON in object storage, loads it into a PostgreSQL warehouse modelled as a star
schema with dbt, tests data quality and flags anomalies, and is orchestrated by Airflow on AWS.

**Why this subject.** It is chapter three of the Corning monitoring arc in `story_bank.md`: the
weekly environmental report automated in VBA against PI System, then the Python monitoring system
with morning alerts, now the same idea rebuilt as a proper data platform. Station telemetry has the
same shape as fab sensor data: a station is a tool, a pollutant is a process parameter, an hourly
reading is a measurement. So the story lands with Micron, TSMC, and Corning-type employers. The data
is live, free, Taiwanese, and updated hourly, so the pipeline has real incremental loads, late
arrivals, and outages to handle rather than a static Kaggle file. The analytic question, how wind
and rain move PM2.5, uses the airflow domain knowledge she already has.

**Sources.** Verify current dataset IDs and key sign-up when starting.

| Source | Platform | Cadence | Notes |
|---|---|---|---|
| Air quality by station: AQI and pollutants | Ministry of Environment 環境部 open data platform, data.moenv.gov.tw | hourly, about 80 stations | free API key; historical hourly datasets exist for backfill |
| Automatic weather station observations | Central Weather Administration 中央氣象署 open data platform, opendata.cwa.gov.tw | 10 minutes to hourly | free API key; join each air-quality station to its nearest weather station |
| Optional stretch: YouBike 2.0 station availability, Taipei | Taipei City open data | about 1 minute, about 1,300 stations | no key; high-frequency feed for the streaming stretch |

**Architecture**

```
Python extractor  ->  raw JSON partitioned by date  (local folder in phases 0 to 3, S3 in phase 4)
       |
       v
PostgreSQL raw schema  (append-only landing tables, idempotent upsert on the natural key)
       |
       v  dbt
staging  ->  intermediate  ->  marts (star schema)
                                 fact_reading, fact_weather
                                 dim_station, dim_pollutant, dim_date, dim_hour
       |
       v
dbt tests + custom anomaly checks  ->  alert (email or Telegram) on failure
       |
       v
Airflow DAG, hourly: extract -> load -> dbt run -> dbt test -> anomaly check -> alert
       |
       v
Metabase dashboard; dbt docs published as the data dictionary
```

## 5. Phases, deliverables, and time

Assumption: about 10 hours per week alongside the remote Dysrupt role and job hunting. Halve the
weeks at 20 hours per week.

| Phase | Build | Learn deliberately | Claimable afterwards | Weeks |
|---|---|---|---|---|
| 0. Design | Public GitHub repo; Docker Compose with Postgres and pgAdmin; API keys; schema sketch; README skeleton with the architecture diagram; decision log started | Kimball star-schema basics: grain, facts, dimensions | nothing yet | 1 |
| 1. Postgres, SQL, modelling | Extractor with retries and idempotent upsert; raw tables; star schema built with hand-written SQL; backfill one year of history; fact table partitioned by month; indexes; roles and grants; pg_dump backup and restore | Window functions, CTEs, EXPLAIN ANALYZE, partitioning, transactions, upsert semantics | PostgreSQL, SQL, dimensional modelling, database operation | 3 |
| 2. dbt | Convert transforms to dbt models in staging, intermediate, marts layers; sources with freshness checks; schema tests (not_null, unique, accepted_values, relationships) plus custom tests for value ranges, duplicate hours, missing stations; snapshot for the station dimension; dbt docs generated | ELT layering, incremental models, testing strategy, lineage | dbt, data quality testing, data dictionary and metadata | 2 |
| 3. Airflow | Airflow in Docker Compose; hourly DAG: extract, load, dbt run, dbt test, anomaly check, alert; catchup and backfill; retries and timeouts; SLA-miss callback; alert channel; idempotent tasks | DAG design, scheduling semantics, backfill, idempotency, observability | Airflow, orchestration, monitoring and alerting | 2 |
| 4. AWS | S3 landing zone with date partitions and a lifecycle rule; RDS PostgreSQL; Airflow on a small EC2 via Docker Compose; IAM roles with least privilege; Secrets Manager or SSM for keys; CloudWatch logs and one alarm; billing alarm on day one; optional Terraform for all of it | IAM model, VPC and security-group basics, managed-database trade-offs, cost control | AWS: S3, RDS, EC2, IAM, CloudWatch; Terraform if done | 2 to 3 |
| 5. Polish and publish | README with diagram, decision log, data dictionary link; dbt docs on GitHub Pages; Metabase dashboard screenshots; GitHub Actions running ruff, pytest, and dbt build on every push; short write-up; update fact sheet, story bank, and CV | CI/CD, technical writing | CI/CD, documentation | 1 |

Total: about 11 to 12 weeks, roughly 110 to 120 hours.

**Fast track for an active job search (recommended, decided 2026-09-05).** The full schedule is
too long while applications are live. Use this instead; the full table stays as the reference for
what each phase can contain.

| Phase | Weeks | What is cut |
|---|---|---|
| 0 + 1. Design, Postgres, SQL, modelling | 3 | nothing; this is the core and the biggest gap |
| 2. dbt | 1.5 | skip snapshots; models, tests, docs only |
| 3. Airflow | 1.5 | one DAG with retries, backfill, one alert channel; skip SLA callbacks |
| 4. AWS minimal | 1 | S3 landing zone, RDS Postgres, IAM, billing alarm; Airflow stays local; no EC2, no Terraform |
| 5. Polish | continuous | README and decision log written as you go; Metabase optional; GitHub Actions only if time remains |

Total: about 7 weeks at 10 hours per week, about 5 weeks at 15. Put the project on the CV as an
ongoing project at the end of phase 1 (week 3). Stop wherever an offer lands; the repo is evidence
at any stage.

**Update the CV at three checkpoints, not at the end.**

- End of phase 1 (week 4): add PostgreSQL and dimensional modelling.
- End of phase 3 (week 8): add dbt, Airflow, data quality testing; remove them from the
  never-claim list.
- End of phase 4 (week 11): add the AWS services by name.

Each checkpoint also gets a story-bank block and a Projects entry in the fact sheet.

**Stretch, in this order, only after phase 5:**

1. Snowflake 30-day trial as a second dbt target (about 1 week). Start the trial only when ready
   so the window is not wasted. Covers Micron's Smart Manufacturing posting and fatsecret.
   BigQuery is the alternative if a permanent free tier matters more.
2. Streaming feed (about 2 weeks): Redpanda or Kafka in Docker, a producer polling YouBike every
   minute, a consumer writing to Postgres. Answers Micron's batch-plus-streaming line. Keep it
   small.
3. Terraform for the AWS resources (about 1 week) if not done in phase 4.

## 6. Parallel track: SQL interview practice

From phase 1 onward, 30 minutes a day on SQL problems (DataLemur, StrataScratch, or LeetCode SQL).
Screening tests for Taiwan data roles are usually SQL. The project builds depth; the drills build
speed.

## 7. Rules for the build

- Everything local in Docker through phase 3. Cloud only in phase 4. This keeps focus and cost
  down.
- Set an AWS billing alarm before creating any other resource. Check the current free-tier terms at
  sign-up because they changed in 2025. Keep the monthly cap small, and tear down EC2 and RDS after
  capturing screenshots, or keep them for one month as a live demo while interviewing.
- Interviewers probe idempotency, backfill, late data, and testing. Do those properly before
  adding any tool.
- Keep a decision log in the repo: why Postgres, why star schema, why Airflow, why this grain.
  Micron asks for technology selection and documentation; the log is the evidence.
- No secrets in the repo. Public repo, small commits, meaningful messages.
- Do not add a tool to `fact_sheet.md` until the phase is finished and the tool has run in the
  pipeline for real. The never-claim list stays as is until then.

## 8. The interview story this produces

At Corning the weekly environmental monitoring report was assembled by hand from the PI System, so
she automated it in VBA, then rebuilt it in Python as a shared alerting system when the supervisor
asked to scale it. For this project she rebuilt the same idea as a data platform: hourly ingestion
of Taiwan's public air-quality and weather feeds, a PostgreSQL warehouse modelled as a star schema
with dbt, quality tests and anomaly alerts, orchestrated by Airflow and deployed on AWS. Station
telemetry has the same shape as fab sensor data, so the pitch to Micron or TSMC is direct.

## 9. Repo and concrete scope (added 2026-09-05)

**Separate repo.** Build this in its own public GitHub repo, not inside CV-generator. CV-generator
holds private material (phone numbers, fact sheet, application history) and must stay private; the
portfolio repo is what recruiters open, so it must be public and clean. This repo lives at
`~/workspace/tw-air-quality-pipeline`; this file is `PLAN.md` at its root. CV-generator keeps no copy;
its memory note points here.

**Who it is for.** Imagine an environmental monitoring engineer (the Corning role). Every morning
she wants to know:

- Which stations exceeded the PM2.5 limit yesterday, and for how many hours?
- What is each county's AQI trend this month, and how does it compare with the same month last year?
- How does PM2.5 move when wind speed or rainfall changes?
- Which stations have bad data: missing hours, negative values, the same value for six hours in a row?

**What runs every hour.**

1. Extract: call the Ministry of Environment API for the latest hourly reading from about 80
   stations (PM2.5, PM10, O3, CO, SO2, NO2, AQI). Phase 2 adds the Central Weather
   Administration API (temperature, humidity, wind speed, wind direction, rainfall).
2. Land raw: save the API JSON unchanged, one folder per date. This is the lake layer; any later
   step can be re-run from it.
3. Load: flatten the JSON into Postgres raw tables. Re-fetching the same station and hour must not
   create a second row.
4. Transform (dbt): build the star schema. `dim_station` (name, county, lat/lon, nearest weather
   station), `dim_pollutant` (code, unit, legal limit), `dim_date`, `fact_air_reading` (one row per
   station, hour, pollutant), plus daily and monthly aggregates and an exceedance-event table.
5. Test: keys not null, station plus hour unique, values within range, every station present for
   the hour, newest data no older than two hours.
6. Alert: a station jumps more than three standard deviations, or reports the same value for six
   consecutive hours, sends an email or Telegram message. This is the Corning alert email rebuilt.
7. Orchestrate: steps 1 to 6 as one Airflow DAG, hourly, with retries and date-range backfill.
8. Dashboard (Metabase): county monthly trend, exceedance ranking, wind speed versus PM2.5
   scatter, per-station data-quality status.
9. Cloud (phase 4): JSON to S3, Postgres to RDS, Airflow on EC2.

**Definition of done.** A public repo with an architecture diagram and decision log in the README;
a DAG that has run hourly for several weeks; at least one year of history in Postgres; dbt docs
published as the data dictionary; Metabase screenshots.

**MVP scoping.** Phase 1 ingests air quality only. Add the weather source at the start of phase 2,
when the loader pattern is already proven. Interviewers will probe steps 3, 5, 6, and 7
(deduplication, backfill, detecting broken data), not the dashboard.
