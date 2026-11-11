import os
import json
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from airflow.providers.slack.operators.slack_webhook import SlackWebhookOperator

# DAG configuration – runs nightly at 02:00 UTC
default_args = {
    "owner": "mariana",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    "latency_monitoring_dag",
    default_args=default_args,
    description="Run dbt models to calculate shipment latency",
    schedule_interval="0 2 * * *",
    start_date=datetime(2023, 1, 1),
    catchup=False,
)

# Step 1: dbt run
run_dbt = BashOperator(
    task_id="run_dbt",
    bash_command="cd {{ var.value.dbt_project_path }} && dbt run",
    dag=dag,
)

# Step 2: Validate that the fact view has rows
def validate_fact(**context):
    bq = BigQueryHook(gcp_conn_id="google_cloud_default", use_legacy_sql=False)
    sql = "SELECT COUNT(*) as cnt FROM `{{ var.value.bq_project }}.{{ var.value.bq_dataset }}.shipment_latency`"
    records = bq.get_records(sql)
    count = records[0][0] if records else 0
    if count == 0:
        raise ValueError("Fact view shipment_latency is empty after dbt run")
    return count

validate = PythonOperator(
    task_id="validate_fact",
    python_callable=validate_fact,
    provide_context=True,
    dag=dag,
)

# Step 3: Slack notification on success
notify_success = SlackWebhookOperator(
    task_id="notify_success",
    http_conn_id="slack_webhook",
    webhook_token=os.getenv("SLACK_WEBHOOK_TOKEN"),
    message="✅ Shipment latency pipeline completed successfully at {{ ds }}",
    username="airflow",
    dag=dag,
)

# Step 4: Slack notification on failure (handled via on_failure_callback)
def failure_callback(context):
    SlackWebhookOperator(
        task_id="notify_failure",
        http_conn_id="slack_webhook",
        webhook_token=os.getenv("SLACK_WEBHOOK_TOKEN"),
        message=f"❗️ Latency pipeline failed: {context['exception']}",
        username="airflow",
    ).execute(context=context)

run_dbt.on_failure_callback = failure_callback
validate.on_failure_callback = failure_callback

run_dbt >> validate >> notify_success
