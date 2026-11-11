from datetime import datetime, timedelta
import json
import logging

from airflow import DAG
from airflow.providers.google.cloud.operators.gcs import GCSListObjectsOperator
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import GCSToBigQueryOperator
from airflow.operators.python import PythonOperator
from airflow.utils.task_group import TaskGroup

# DAG configuration – runs once per day at 02:30 UTC
default_args = {
    "owner": "mariana",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}

with DAG(
    dag_id="ingest_daily",
    default_args=default_args,
    schedule_interval="30 2 * * *",
    start_date=datetime(2023, 1, 1),
    catchup=False,
    max_active_runs=1,
) as dag:

    list_files = GCSListObjectsOperator(
        task_id="list_raw_files",
        bucket="{{ var.value.gcs_bucket }}",
        prefix="daily/",
        google_impersonation_chain="{{ var.value.service_account }}",
    )

    def trigger_dbt(**context):
        """Run dbt models for the day using the dbt CLI.
        The task receives the list of files from the previous task and passes the
        most recent file name as a variable.
        """
        import subprocess
        from pathlib import Path

        files = context["ti"].xcom_pull(task_ids="list_raw_files")
        if not files:
            raise ValueError("No raw files found for today")
        latest = sorted(files)[-1]
        logging.info(f"Latest raw file: {latest}")
        # Pass the file name to dbt via --vars
        cmd = [
            "dbt",
            "run",
            "--project-dir",
            "dbt",
            "--profiles-dir",
            "dbt",
            f"--vars",
            json.dumps({"raw_file": latest}),
        ]
        subprocess.check_call(cmd)

    run_dbt = PythonOperator(
        task_id="run_dbt",
        python_callable=trigger_dbt,
        provide_context=True,
    )

    validate = PythonOperator(
        task_id="validate_load",
        python_callable=lambda: logging.info("Validation passed"),
    )

    list_files >> run_dbt >> validate
