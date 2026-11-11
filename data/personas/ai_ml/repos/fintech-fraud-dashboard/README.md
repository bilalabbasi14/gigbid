# Fraud Detection Dashboard (fintech-fraud-dashboard)

**Project Overview**

This repository contains the core components of an enterprise‑grade fraud detection system built for a large fintech client in 2022. The solution combines a gradient‑boosted tree model (XGBoost) with a robust MLOps pipeline to continuously improve detection performance while keeping operational overhead low.

**Architecture**

- **Data Ingestion** – Transaction logs are landed daily in an S3 bucket. An Airflow DAG (`dag_fraud_retrain.py`) pulls the new parquet files, runs a feature engineering step (`features.py`) and stores the enriched dataset back to S3.
- **Model Training** – `train.py` reads the engineered data, trains an XGBoost classifier, and logs the model, parameters, and metrics to an MLflow tracking server. The trained model artifact is then pushed to AWS SageMaker Model Registry for serving.
- **Serving** – A lightweight FastAPI wrapper (not included) loads the SageMaker‑registered model for real‑time scoring. Batch scoring jobs are also orchestrated via Airflow.
- **Containerisation** – All components run inside Docker images defined in `Dockerfile`. The images are built and pushed to ECR as part of the CI/CD pipeline (GitHub Actions, not shown).

**Setup**

1. Install dependencies: `pip install -r requirements.txt`.
2. Configure environment variables for S3 access, MLflow tracking URI, and SageMaker role.
3. Initialise the Airflow environment and place `dag_fraud_retrain.py` in the DAGs folder.
4. Run `python train.py --date 2022-12-01` to execute a one‑off training run.

**Key Results**

- False‑positive rate reduced from **4.3 %** to **1.7 %**.
- Detected fraudulent transaction volume increased by **22 %**.
- Nightly retraining cut model drift lag from 7 days to under 24 hours.

**License** – MIT (see LICENSE).

---
*Priya Raman – ML Engineer*
