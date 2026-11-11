import os
import argparse
from datetime import datetime
from google.cloud import bigquery
import pandas as pd

def fetch_listings(target_date: str) -> pd.DataFrame:
    client = bigquery.Client()
    query = f"""
        SELECT
            listing_id,
            price,
            bedrooms,
            bathrooms,
            latitude,
            longitude,
            zip_code,
            property_type,
            DATE(listing_date) AS listing_date
        FROM `myproject.realestate.mls_listings`
        WHERE DATE(listing_date) = @target_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("target_date", "DATE", target_date)]
    )
    df = client.query(query, job_config=job_config).to_dataframe()
    return df

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract MLS listings for a given date.")
    parser.add_argument("--date", required=True, help="Target date in YYYY-MM-DD format")
    args = parser.parse_args()
    df = fetch_listings(args.date)
    output_path = os.path.join("data", f"listings_{args.date}.parquet")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_parquet(output_path, index=False)
    print(f"Saved {len(df)} rows to {output_path}")
