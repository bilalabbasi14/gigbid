import os
import argparse
import pandas as pd
import xgboost as xgb
import mlflow
import mlflow.xgboost
from features import engineer_features

def load_data(date_str: str) -> pd.DataFrame:
    s3_path = f"s3://fintech-data/transactions/{date_str}/transactions.parquet"
    return pd.read_parquet(s3_path)

def main():
    parser = argparse.ArgumentParser(description="Train fraud detection model")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD for the training batch")
    args = parser.parse_args()

    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
    mlflow.set_experiment("fraud-detection")

    with mlflow.start_run():
        df = load_data(args.date)
        X, y = engineer_features(df)
        dtrain = xgb.DMatrix(X, label=y)
        params = {
            "objective": "binary:logistic",
            "eval_metric": "auc",
            "max_depth": 6,
            "eta": 0.1,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "seed": 42,
        }
        mlflow.log_params(params)
        model = xgb.train(params, dtrain, num_boost_round=150)
        mlflow.xgboost.log_model(model, "model")
        # Simple evaluation
        preds = model.predict(dtrain)
        pred_labels = (preds > 0.5).astype(int)
        fp = ((pred_labels == 1) & (y == 0)).sum()
        tn = ((pred_labels == 0) & (y == 0)).sum()
        fpr = fp / (fp + tn)
        mlflow.log_metric("false_positive_rate", fpr)
        print(f"Logged model with FPR={fpr:.4f}")

if __name__ == "__main__":
    main()
