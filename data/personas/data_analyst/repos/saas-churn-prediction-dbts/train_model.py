import os
import json
import argparse
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score, classification_report
from xgboost import XGBClassifier
from google.cloud import bigquery


def load_features_from_bq(project_id: str, dataset: str, table: str, label_column: str = 'churned_30d') -> pd.DataFrame:
    """Pull the full feature matrix from BigQuery."""
    client = bigquery.Client(project=project_id)
    query = f"""
        SELECT *
        FROM `{project_id}.{dataset}.{table}`
        WHERE churned_30d IS NOT NULL
    """
    df = client.query(query).to_dataframe(create_bqstorage_client=False)
    print(f"Loaded {len(df)} rows, {df.shape[1]} columns from BigQuery")
    return df


def prepare_features(df: pd.DataFrame, label_column: str = 'churned_30d'):
    """Separate features and label, handle missing values."""
    y = df[label_column].astype(int)
    feature_cols = [c for c in df.columns if c not in ['user_id', 'created_at', 'last_login_at', 'subscription_start_date', label_column]]
    X = df[feature_cols].copy()
    # Fill numeric NaNs with median
    for col in X.select_dtypes(include=[np.number]).columns:
        X[col] = X[col].fillna(X[col].median())
    # Encode categorical plan_tier
    X['plan_tier_encoded'] = X['plan_tier'].map({'free': 0, 'starter': 1, 'pro': 2, 'enterprise': 3}).fillna(1)
    X = X.drop(columns=['plan_tier'], errors='ignore')
    return X, y


def train_and_evaluate(X: pd.DataFrame, y: pd.Series):
    """Train XGBoost, evaluate F1, return model and metrics."""
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    model = XGBClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric='logloss',
        random_state=42,
        use_label_encoder=False
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    y_pred = model.predict(X_val)
    f1 = f1_score(y_val, y_pred)
    print(f"Validation F1-score: {f1:.4f}")
    print(classification_report(y_val, y_pred))
    return model, f1


def save_artifacts(model, feature_importances: dict, output_dir: str = 'artifacts'):
    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(output_dir, 'churn_model.json')
    model.save_model(model_path)
    with open(os.path.join(output_dir, 'feature_importance.json'), 'w') as f:
        json.dump(feature_importances, f, indent=2)
    print(f"Model saved to {model_path}")


def main():
    parser = argparse.ArgumentParser(description='Train churn prediction model')
    parser.add_argument('--project', default=os.environ.get('GOOGLE_CLOUD_PROJECT', 'your-project'))
    parser.add_argument('--dataset', default='analytics')
    parser.add_argument('--table', default='churn_features')
    args = parser.parse_args()

    df = load_features_from_bq(args.project, args.dataset, args.table)
    X, y = prepare_features(df)
    model, f1 = train_and_evaluate(X, y)

    importance = dict(zip(X.columns, model.feature_importances_))
    importance = {k: float(v) for k, v in sorted(importance.items(), key=lambda x: -x[1])[:15]}
    print("Top 15 features by importance:")
    for feat, score in importance.items():
        print(f"  {feat}: {score:.4f}")

    save_artifacts(model, importance)


if __name__ == '__main__':
    main()
