# Logistics Latency DBT & Airflow Pipeline

**Project:** Supply chain latency monitoring (2023) – 7‑week engagement for a logistics agency.

## Overview
The goal was to give operations teams real‑time visibility into shipment latency so they could intervene before delivery windows were missed. We built a lightweight data pipeline that extracts raw shipment events from a BigQuery staging table, transforms them with dbt into a clean latency fact, and surfaces the results to a Power BI dashboard.

## Architecture
1. **Ingestion** – Raw event logs (`shipment_events_raw`) are already landing in BigQuery via the agency’s upstream ETL.
2. **Transformation** – A dbt project (`latency_dbt`) defines a staging model (`stg_shipment_events.sql`) and a fact model (`fact_shipment_latency.sql`). The fact model calculates `delivery_delay_minutes` and flags late deliveries.
3. **Orchestration** – An Airflow DAG (`latency_monitoring_dag.py`) runs nightly at 02:00 UTC. It:
   - Triggers `dbt run` for the `latency_dbt` project.
   - Executes a validation query via the BigQuery client.
   - Sends a Slack notification on success/failure.
4. **Reporting** – The `shipment_latency` view is consumed by Power BI, where the team tracks on‑time delivery percentages and trends.

## Setup
```bash
# Clone repo
git clone https://github.com/example/logistics-latency-dbt.git
cd logistics-latency-dbt

# Python env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# dbt profile (~/.dbt/profiles.yml)
#   Use a service account key JSON and set project_id, dataset, and location.

# Airflow
airflow db init
airflow users create --username admin --firstname Mariana --lastname Costa --role Admin --email mariana@example.com
airflow dags list   # verify latency_monitoring_dag appears
```

## Running locally
```bash
# Run dbt models manually
cd dbt
 dbt deps && dbt run

# Trigger the DAG (development)
airflow dags trigger latency_monitoring_dag
```

## Results
- On‑time delivery rose from **78 % to 91 %** within two months.
- Manual reconciliation effort dropped by **~60 %** as the Power BI report auto‑refreshed nightly.

---
*Mariana Costa – Data Engineer / Analyst*
