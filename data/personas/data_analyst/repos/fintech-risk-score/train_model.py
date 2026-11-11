import os
import joblib
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score

# Load feature view from Snowflake using pandas connector
import snowflake.connector

ctx = snowflake.connector.connect(
    user=os.getenv('SF_USER'),
    password=os.getenv('SF_PASSWORD'),
    account=os.getenv('SF_ACCOUNT'),
    warehouse='COMPUTE_WH',
    database='FINTECH_DB',
    schema='PUBLIC'
)
sql = "SELECT * FROM loan_features_vw WHERE loan_status = 'APPROVED'"
features = pd.read_sql(sql, ctx)
ctx.close()

X = features.drop(columns=['loan_id', 'risk_label'])
y = features['risk_label']
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42, stratify=y)

model = GradientBoostingClassifier(n_estimators=200, learning_rate=0.05, max_depth=4, random_state=42)
model.fit(X_train, y_train)

pred_proba = model.predict_proba(X_test)[:, 1]
auc = roc_auc_score(y_test, pred_proba)
print(f"Test ROC‑AUC: {auc:.4f}")

# Serialize model and upload to Snowflake stage
joblib.dump(model, 'model.joblib')
ctx = snowflake.connector.connect(
    user=os.getenv('SF_USER'),
    password=os.getenv('SF_PASSWORD'),
    account=os.getenv('SF_ACCOUNT'),
    warehouse='COMPUTE_WH',
    database='FINTECH_DB',
    schema='PUBLIC'
)
cs = ctx.cursor()
cs.execute("PUT file://model.joblib @my_stage AUTO_COMPRESS=TRUE OVERWRITE=TRUE")
cs.close()
ctx.close()
