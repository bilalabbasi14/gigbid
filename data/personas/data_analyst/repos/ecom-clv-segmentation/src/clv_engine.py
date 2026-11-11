import argparse
import pathlib
import numpy as np
import pandas as pd

from datetime import datetime, timedelta

def load_transactions(path: pathlib.Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    # Ensure correct dtypes
    df['order_date'] = pd.to_datetime(df['order_date'])
    df['order_value'] = df['order_value'].astype(float)
    return df

def rfm_features(df: pd.DataFrame, reference_date: datetime) -> pd.DataFrame:
    recency = df.groupby('customer_id')['order_date'].max().apply(lambda d: (reference_date - d).days)
    frequency = df.groupby('customer_id').size()
    monetary = df.groupby('customer_id')['order_value'].sum()
    rfm = pd.DataFrame({'recency': recency, 'frequency': frequency, 'monetary': monetary})
    return rfm

def calculate_clv(rfm: pd.DataFrame, discount_rate: float = 0.01) -> pd.Series:
    # Simple CLV = monetary * (1 + discount_rate) ** (-recency/365)
    years = rfm['recency'] / 365.0
    clv = rfm['monetary'] * np.exp(-discount_rate * years)
    return clv

def segment_clv(clv: pd.Series) -> pd.Series:
    quantiles = clv.quantile([0.2, 0.4, 0.6, 0.8])
    bins = [-np.inf, quantiles[0.2], quantiles[0.4], quantiles[0.6], quantiles[0.8], np.inf]
    labels = ['Churned', 'At-Risk', 'New', 'Loyal', 'High-Value']
    return pd.cut(clv, bins=bins, labels=labels)

def main():
    parser = argparse.ArgumentParser(description='Calculate CLV and segment customers')
    parser.add_argument('--input', type=pathlib.Path, required=True, help='Path to raw transactions parquet')
    parser.add_argument('--output', type=pathlib.Path, required=True, help='Path to write processed CLV parquet')
    args = parser.parse_args()

    df = load_transactions(args.input)
    ref_date = datetime.utcnow()
    rfm = rfm_features(df, ref_date)
    rfm['clv'] = calculate_clv(rfm)
    rfm['segment'] = segment_clv(rfm['clv'])
    rfm.reset_index(inplace=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rfm.to_parquet(args.output, index=False)
    print(f"Processed {len(rfm)} customers, saved to {args.output}")

if __name__ == '__main__':
    main()
