import os
import argparse
from datetime import datetime, timedelta
import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from google.cloud import bigquery

BQ_PROJECT = os.getenv("BIGQUERY_PROJECT")
client = bigquery.Client(project=BQ_PROJECT)

FEATURE_TABLE = f"{BQ_PROJECT}.analytics.churn_features"
PRED_TABLE = f"{BQ_PROJECT}.analytics.churn_predictions"
MODEL_PATH = "models/churn_lr.joblib"

def load_features(date: str) -> pd.DataFrame:
    query = f"""
        SELECT * FROM `{FEATURE_TABLE}`
        WHERE prediction_date = '{date}'
    """
    return client.query(query).to_dataframe()

def train_model(df: pd.DataFrame):
    X = df.drop(columns=["user_id", "churn"])
    y = df["churn"]
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    model = LogisticRegression(max_iter=200, class_weight="balanced")
    model.fit(X_scaled, y)
    return model, scaler

def predict_and_save(df: pd.DataFrame, model, scaler, date: str):
    X = df.drop(columns=["user_id", "churn"])
    X_scaled = scaler.transform(X)
    probs = model.predict_proba(X_scaled)[:, 1]
    results = pd.DataFrame({
        "user_id": df["user_id"],
        "prediction_date": date,
        "churn_score": probs,
    })
    job = client.load_table_from_dataframe(results, PRED_TABLE)
    job.result()
    print(f"Saved predictions for {len(results)} users to {PRED_TABLE}")

def main(target_date: str):
    # Load features for the day before the target date (lagged features)
    feature_date = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    df = load_features(feature_date)
    if df.empty:
        print("No feature data found, aborting.")
        return
    model, scaler = train_model(df)
    joblib.dump((model, scaler), MODEL_PATH)
    predict_and_save(df, model, scaler, target_date)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train and run churn prediction")
    parser.add_argument("--date", type=str, default=datetime.utcnow().strftime("%Y-%m-%d"), help="Prediction date YYYY-MM-DD")
    args = parser.parse_args()
    main(args.date)
