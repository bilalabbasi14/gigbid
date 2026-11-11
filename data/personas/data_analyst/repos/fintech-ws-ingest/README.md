# fintech-ws-ingest

**Project**: Data warehouse migration – phase 1: ingestion layer (FinTech client, 2023)

This repository contains the code that implements the first phase of a multi‑stage migration from a legacy on‑premise data warehouse to Google BigQuery. The focus is on building a reliable ingestion pipeline that extracts daily product event logs, transforms them with **dbt**, and loads the results into a staging schema in BigQuery. The pipeline is orchestrated by **Apache Airflow** and runs on a GKE‑based Composer environment.

## Architecture

- **Source** – CSV files landed in a GCS bucket (`gs://fintech-raw-data/daily/`).
- **Airflow DAG** – `ingest_daily_dag.py` pulls the manifest, triggers a dbt run, and performs post‑load validation.
- **dbt** – A lightweight dbt project (`dbt/`) defines staging models (`stg_events.sql`) that parse the raw CSV, apply type casts, and generate surrogate keys. The models are materialised as **incremental** tables in BigQuery, using the `bigquery` adapter.
- **BigQuery** – Staging tables live in `fintech_staging` dataset. Downstream teams consume them via BI tools.

## Setup

1. **Clone** the repo and create a virtualenv.
2. Install Python dependencies from `requirements.txt`.
3. Initialise the dbt project:
   ```bash
   cd dbt && dbt deps && dbt seed --target prod
   ```
4. Deploy the Airflow DAG to the Composer environment (copy `dags/ingest_daily_dag.py`).
5. Configure GCP credentials (`GOOGLE_APPLICATION_CREDENTIALS`) and set the Airflow variables `gcs_bucket` and `bq_dataset`.

## Running locally

```bash
# Run dbt models directly
cd dbt && dbt run --target dev

# Trigger the Airflow DAG (requires a local Airflow instance)
airflow dags trigger ingest_daily
```

## Results

- **Data latency** dropped from 24 h to ~2 h.
- **Storage cost** decreased 18 % thanks to partitioned tables and column pruning.
- The codebase follows the client’s CI/CD guidelines (pytest coverage ≥ 85 %).

---

*Mariana Costa – Data Engineer*
