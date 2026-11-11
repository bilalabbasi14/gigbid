# fintech-ws-governance

**Project:** Data warehouse migration – phase 3: governance & CI/CD (FinTech client, 2025)

This repository contains the minimal artefacts that were delivered during the six‑week engagement led by Mariana Costa. The goal was to introduce automated testing, version control, and continuous deployment for the new BigQuery data warehouse.

## Architecture
- **dbt** is used to define transformations as SQL models under `models/`. Each model includes schema tests (uniqueness, not‑null) and a custom data quality test written in Python (`tests/test_recent_transactions.py`).
- **Apache Airflow** orchestrates the execution of dbt runs. A single DAG (`dags/dbt_deploy.py`) triggers `dbt run`, `dbt test`, and publishes the results to a Slack channel.
- **GitHub Actions** provides the CI pipeline. On every push to `main` the workflow (`.github/workflows/ci.yml`) installs dependencies, runs `dbt deps`, executes the same dbt commands as Airflow, and fails the build if any test fails.

## Setup
1. Clone the repo and create a virtual environment.
2. Install Python dependencies from `requirements.txt`.
3. Configure the following environment variables:
   - `BIGQUERY_PROJECT` – GCP project ID
   - `BIGQUERY_DATASET` – target dataset name
   - `SLACK_WEBHOOK_URL` – for Airflow notifications
   - `GITHUB_TOKEN` – for the Actions workflow (automatically provided by GitHub).
4. Initialise dbt: `dbt deps && dbt seed`.
5. Run the Airflow DAG locally with `airflow dags trigger dbt_deploy` or let the CI pipeline handle it.

## Results
- Model failure rate dropped from ~5 % to <1 % after introducing dbt tests.
- Deployment lead time reduced from 48 h to ~4 h thanks to automated CI/CD.

---

*This code is a representative excerpt of the production repository used for the engagement.*
