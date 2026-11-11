from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta

default_args = {
    "owner": "ml_engineer",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    "fraud_retrain",
    default_args=default_args,
    description="Nightly retraining of fraud detection model",
    schedule_interval="@daily",
    start_date=datetime(2022, 1, 1),
    catchup=False,
)

train_task = BashOperator(
    task_id="train_model",
    bash_command="python /opt/airflow/scripts/train.py --date {{ ds }}",
    dag=dag,
)

train_task
