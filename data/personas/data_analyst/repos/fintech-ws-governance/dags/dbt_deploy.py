from airflow import DAG
from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator
from airflow.operators.bash import BashOperator
from airflow.utils.dates import days_ago
from airflow.providers.slack.operators.slack_webhook import SlackWebhookOperator

default_args = {
    'owner': 'mariana.costa',
    'retries': 1,
    'retry_delay': 300,
}

dag = DAG(
    dag_id='dbt_deploy',
    default_args=default_args,
    schedule_interval='@daily',
    start_date=days_ago(1),
    catchup=False,
)

install_deps = BashOperator(
    task_id='install_deps',
    bash_command='pip install -r /opt/airflow/dbt_requirements.txt',
    dag=dag,
)

run_dbt = BashOperator(
    task_id='dbt_run',
    bash_command='cd /opt/airflow/dbt && dbt run --profiles-dir .',
    dag=dag,
)

test_dbt = BashOperator(
    task_id='dbt_test',
    bash_command='cd /opt/airflow/dbt && dbt test --profiles-dir .',
    dag=dag,
)

notify_success = SlackWebhookOperator(
    task_id='notify_success',
    http_conn_id='slack_webhook',
    webhook_token=os.getenv('SLACK_WEBHOOK_URL'),
    message='✅ dbt deployment succeeded',
    dag=dag,
)

notify_failure = SlackWebhookOperator(
    task_id='notify_failure',
    http_conn_id='slack_webhook',
    webhook_token=os.getenv('SLACK_WEBHOOK_URL'),
    message='❌ dbt deployment failed',
    trigger_rule='one_failed',
    dag=dag,
)

install_deps >> run_dbt >> test_dbt
(test_dbt >> notify_success) & (test_dbt >> notify_failure)
