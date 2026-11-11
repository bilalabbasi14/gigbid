## Enterprise Data Warehouse Migration & dbt Governance

This repository contains the production data pipeline infrastructure for a SaaS client migrating from ad-hoc SQL scripts to a governed dbt project on BigQuery. The system was designed to support a team of five analysts, resolving data inconsistencies and performance bottlenecks caused by unmanaged query dependencies.

### Architecture

1. **Orchestration**: Apache Airflow DAGs manage the execution order of dbt models, ensuring strict dependency management. Airflow tasks are dynamically generated based on dbt model dependencies.
2. **Transformation**: dbt-core executes the SQL transformations. Models are organized by layer (staging, intermediate, marts) with enforced testing standards.
3. **Quality & Monitoring**: Custom Python hooks integrate with BigQuery to run data quality checks. Failures trigger automated alerts via Slack, reducing incident resolution time from 4 hours to 30 minutes.
4. **Performance**: Optimized SQL patterns and BigQuery partitioning have reduced average query execution time by 40% compared to the legacy script environment.

### Setup

1. Clone the repository.
2. Configure environment variables in `.env` for BigQuery credentials (`GOOGLE_APPLICATION_CREDENTIALS`) and Slack webhook URL.
3. Install dependencies: `pip install -r requirements.txt`.
4. Deploy the Airflow DAGs to your Kubernetes or Dockerized Airflow instance.
5. Run dbt commands via the Airflow operator to execute the pipeline.

### Testing

Unit tests for dbt models are executed using `pytest-dbt`. Run locally with `pytest tests/` to validate schema changes before deployment.
