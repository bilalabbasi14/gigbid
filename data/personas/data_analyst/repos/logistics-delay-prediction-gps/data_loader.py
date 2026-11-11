import pandas as pd
from google.cloud import bigquery
import os
from datetime import datetime, timedelta

class BigQueryLoader:
    def __init__(self, project_id=None):
        self.client = bigquery.Client(project=project_id or os.getenv('GCP_PROJECT'))
        
    def fetch_gps_events(self, start_date, end_date):
        query = f"""
            SELECT 
                shipment_id,
                timestamp,
                lat,
                lon,
                speed_kmh,
                traffic_density_score,
                weather_condition
            FROM `logistics_data.gps_events`
            WHERE timestamp >= '{start_date}'
              AND timestamp < '{end_date}'
        """
        return self.client.query(query).to_dataframe()

    def fetch_delivery_metrics(self, start_date, end_date):
        query = f"""
            SELECT 
                shipment_id,
                scheduled_delivery_ts,
                actual_delivery_ts,
                customer_region
            FROM `logistics_data.deliveries`
            WHERE scheduled_delivery_ts >= '{start_date}'
              AND scheduled_delivery_ts < '{end_date}'
        """
        return self.client.query(query).to_dataframe()

    def merge_datasets(self, gps_df, delivery_df):
        merged = pd.merge(gps_df, delivery_df, on='shipment_id', how='left')
        merged['delay_minutes'] = (merged['actual_delivery_ts'] - merged['scheduled_delivery_ts']).dt.total_seconds() / 60
        return merged.dropna(subset=['delay_minutes'])

if __name__ == "__main__":
    loader = BigQueryLoader()
    end = datetime.now()
    start = end - timedelta(days=90)
    gps = loader.fetch_gps_events(start.isoformat(), end.isoformat())
    deliv = loader.fetch_delivery_metrics(start.isoformat(), end.isoformat())
    final_df = loader.merge_datasets(gps, deliv)
    print(f"Loaded {len(final_df)} records for analysis.")
