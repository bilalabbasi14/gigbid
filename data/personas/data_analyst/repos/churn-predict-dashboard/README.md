# Customer Churn Predictive Dashboard (p01)

**Project Overview**

This repository contains the end‑to‑end implementation of a churn‑prediction solution built for a SaaS startup in 2020. Over a six‑week engagement, the team delivered a reproducible data pipeline that extracts raw usage logs from **Google BigQuery**, transforms them with **pandas** and **scikit‑learn**, and writes a feature table back to BigQuery. A **Power BI Desktop** report consumes that table and visualises churn risk scores, cohort retention, and upsell opportunities using custom **DAX** measures.

**Architecture**

1. **Ingestion** – `src/ingest.py` runs a scheduled Cloud Scheduler job that executes a parameterised SQL query against BigQuery, pulling the last 30 days of user activity.
2. **Feature Engineering & Modeling** – `src/model.py` loads the raw data into pandas, creates behavioural features (e.g., `avg_session_length`, `feature_usage_ratio`), and trains a logistic regression model with scikit‑learn. The trained model is serialized with joblib and the predictions are written back to a `churn_predictions` table in BigQuery.
3. **Reporting** – The Power BI file (`dashboard/ChurnDashboard.pbix`) connects to the `churn_predictions` view. DAX measures defined in `dashboard/measures.dax` compute cohort churn rates, month‑over‑month retention, and projected upsell revenue.

**Setup**

```bash
# Clone the repo
git clone https://github.com/example/churn-predict-dashboard.git
cd churn-predict-dashboard

# Create a virtual environment and install Python deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure credentials (service account JSON) and set environment variables
export GOOGLE_APPLICATION_CREDENTIALS=path/to/service_account.json
export BIGQUERY_PROJECT=my‑gcp‑project

# Run the pipeline (example for a single day)
python src/ingest.py --date 2020-06-01
python src/model.py --date 2020-06-01
```

**Key Results**

- Churn reduced by **12 %** within three months of deployment.
- Upsell opportunities identified increased by **8 %**.
- Dashboard refreshes nightly, providing the product team with actionable risk scores.

**Future Work**

- Replace the static logistic regression with an XGBoost model for higher AUC.
- Add automated model monitoring using Great Expectations.
- Expand the Power BI report with a drill‑through to individual customer timelines.

---
*Lead Data Analyst: Mariana Costa*
