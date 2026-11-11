import os
import pandas as pd
from dbt.adapters.bigquery import BigQueryAdapter


def test_no_future_transactions():
    """Ensures no transaction timestamp is in the future."""
    project = os.getenv('BIGQUERY_PROJECT')
    dataset = os.getenv('BIGQUERY_DATASET')
    query = f"""
        SELECT ts FROM `{project}.{dataset}.stg_transactions`
        WHERE ts > CURRENT_TIMESTAMP()
    """
    adapter = BigQueryAdapter()
    df = adapter.execute(query).to_dataframe()
    assert df.empty, f"Found {len(df)} future transactions"


def test_recent_volume():
    """Checks that daily transaction volume is within expected bounds (90‑110 % of historical average)."""
    project = os.getenv('BIGQUERY_PROJECT')
    dataset = os.getenv('BIGQUERY_DATASET')
    query = f"""
        WITH daily AS (
            SELECT DATE(ts) AS day, SUM(amount) AS total
            FROM `{project}.{dataset}.stg_transactions`
            GROUP BY day
        ), stats AS (
            SELECT AVG(total) AS avg_total, STDDEV(total) AS std_total
            FROM daily
            WHERE day < DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        )
        SELECT d.day, d.total, s.avg_total, s.std_total
        FROM daily d, stats s
        WHERE d.day >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    """
    adapter = BigQueryAdapter()
    df = adapter.execute(query).to_dataframe()
    for _, row in df.iterrows():
        lower = row['avg_total'] * 0.9
        upper = row['avg_total'] * 1.1
        assert lower <= row['total'] <= upper, f"Volume out of bounds on {row['day']}"
