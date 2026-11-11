from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import subprocess
import os

DEFAULT_ARGS = {
    'owner': 'priyaa',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

def preprocess_data(**context):
    # Simple placeholder that runs a shell script to clean raw CSVs
    raw_path = os.getenv('S3_RAW_PATH')
    clean_path = os.getenv('S3_CLEAN_PATH')
    subprocess.check_call([
        'python', 'src/preprocess.py',
        '--input', raw_path,
        '--output', clean_path
    ])

def train_model(**context):
    clean_path = os.getenv('S3_CLEAN_PATH')
    run_name = f"airflow-retrain-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    subprocess.check_call([
        'python', 'src/train_lstm.py',
        '--data-path', clean_path,
        '--run-name', run_name,
        '--epochs', '15'
    ])

with DAG(
    dag_id='assembly_maintenance_pipeline',
    default_args=DEFAULT_ARGS,
    description='ETL + daily LSTM retraining for assembly line sensors',
    schedule_interval='@daily',
    start_date=datetime(2024, 1, 1),
    catchup=False,
) as dag:
    t1 = PythonOperator(
        task_id='preprocess',
        python_callable=preprocess_data,
    )
    t2 = PythonOperator(
        task_id='train',
        python_callable=train_model,
    )
    t1 >> t2
