import pandas as pd
import numpy as np
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer

numeric_cols = ["amount", "hour_of_day", "day_of_week"]
cat_cols = ["merchant_category", "card_type", "country"]

encoder = ColumnTransformer(
    [
        ("num", "passthrough", numeric_cols),
        ("cat", OneHotEncoder(handle_unknown="ignore"), cat_cols),
    ]
)

def engineer_features(df: pd.DataFrame):
    # Basic cleaning
    df = df.copy()
    df["hour_of_day"] = pd.to_datetime(df["timestamp"]).dt.hour
    df["day_of_week"] = pd.to_datetime(df["timestamp"]).dt.dayofweek
    # Target variable
    y = df["is_fraud"].astype(int)
    X_raw = df[numeric_cols + cat_cols]
    X_enc = encoder.fit_transform(X_raw)
    # Convert to dense array for XGBoost compatibility
    X = X_enc.toarray() if hasattr(X_enc, "toarray") else X_enc
    return X, y
