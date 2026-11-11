import os
import argparse
from datetime import datetime, timedelta
from google.cloud import bigquery
import pandas as pd

BQ_PROJECT = os.getenv("BIGQUERY_PROJECT")
client = bigquery.Client(project=BQ_PROJECT)

def fetch_usage(date: str) -> pd.DataFrame:
    """Pull raw usage events for the given date from BigQuery."""
    query = f"""
        SELECT
            user_id,
            event_timestamp,
            event_type,
            session_id,
            feature_name
        FROM `my_dataset.user_events`
        WHERE DATE(event_timestamp) = '{date}'
    """
    df = client.query(query).to_dataframe()
    return df

def main(target_date: str):
    df = fetch_usage(target_date)
    # Write raw snapshot to a staging table for downstream processing
    table_id = f"{BQ_PROJECT}.staging.raw_events_{target_date.replace('-', '')}"
    job = client.load_table_from_dataframe(df, table_id)
    job.result()
    print(f"Ingested {len(df)} rows for {target_date} into {table_id}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest daily usage data")
    parser.add_argument("--date", type=str, default=(datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"), help="YYYY-MM-DD")
    args = parser.parse_args()
    main(args.date)
