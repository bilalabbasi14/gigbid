This repository contains the data pipeline and modeling code for a SaaS churn prediction system. The project was built for a Series A SaaS startup to help their CTO prioritize support outreach by identifying high-risk users.

## Architecture

The system has three main components:

1. **dbt Models (BigQuery)**: A dbt project that transforms raw event and subscription data in BigQuery into a feature store. The `stg_` models clean and deduplicate source tables, while the `marts_` models calculate 40+ behavioral features (login frequency, feature adoption, support ticket counts, etc.) at a 30-day window for each user.

2. **ML Pipeline (Python)**: A script that pulls the feature matrix from BigQuery, trains an XGBoost classifier, and exports the model along with feature importance scores. The model was tuned to achieve an 82% F1-score on the validation set.

3. **Power BI Dashboard**: Not included in this repo (proprietary .pbix file), but the `predictions` table in BigQuery is the direct data source. The dashboard segments users into Low/Medium/High risk buckets and displays SHAP-style feature contributions for individual predictions.

## Setup

- Install dependencies: `pip install -r requirements.txt`
- Configure BigQuery credentials via `GOOGLE_APPLICATION_CREDENTIALS` environment variable
- Run dbt: `dbt build --target prod --project-dir dbt_project`
- Train model: `python train_model.py --dataset bigquery://your-project.analytics.churn_features`

## Key Results

- 82% F1-score on validation set
- 14% reduction in 30-day churn in the first quarter post-launch
