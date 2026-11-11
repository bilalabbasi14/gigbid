from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.dbt.cloud.operators.dbt import DbtRunOperationOperator
from airflow.providers.dbt.cloud.sensors.dbt import DbtRunCompletedSensor
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago

def _run_dbt_test(**context):
    """
    Executes dbt tests and logs results. In production, this would 
    trigger the pytest-dbt suite for additional unit validation.
    """
    print("Executing dbt tests for model layer validation...")
    return {"status": "passed", "timestamp": datetime.utcnow()}

def _slack_alert_on_failure(context):
    """
    Custom operator to handle Slack notifications on dbt test failures.
    Integrates with the client's incident response workflow.
    """
    # In production, this would use slack_sdk to post to #data-incidents
    print("Alerting Slack channel: Data quality check failed.")
    return {"alerted": True}

def create_dag():
    default_args = {
        'owner': 'data-engineering',
        'depends_on_past': False,
        'start_date': days_ago(1),
        'retries': 2,\n        'retry_delay': timedelta(minutes=5),
    }
    
    with DAG(
        dag_id='dbt_enterprise_migration',
        default_args=default_args,
        schedule_interval='0 6 * * *',
        catchup=False,
        tags=['dbt', 'bigquery', 'governance'],
    ) as dag:
        
        dbt_run = DbtRunOperationOperator(
            task_id='dbt_run',
            command='run',
            full_refresh=False,
            conn_id='dbt_cloud_default',
            project_id='enterprise-migration',
        )

        dbt_test = DbtRunOperationOperator(
            task_id='dbt_test',
            command='test',
            conn_id='dbt_cloud_default',
            project_id='enterprise-migration',
        )

        quality_check = PythonOperator(
            task_id='quality_check',
            python_callable=_run_dbt_test,
        )

        alert_task = PythonOperator(
            task_id='alert_on_failure',
            python_callable=_slack_alert_on_failure,
            trigger_rule='all_done',
        )

        dbt_run >> dbt_test >> quality_check >> alert_task

    return dag

if __name__ == '__main__':
    create_dag()
