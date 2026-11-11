# Predictive Maintenance for Assembly Lines

**Repository:** `assembly-maintenance-forecast`

This project implements a predictive‑maintenance pipeline for a large automotive assembly line. Sensor data (vibration, temperature, current) is streamed from PLCs into an S3 bucket. A daily Airflow DAG pulls the latest CSV files, performs feature engineering, and stores a cleaned Parquet dataset back to S3. The core forecasting model is an LSTM built with PyTorch that predicts the next 24‑hour sensor trajectory. Model training, validation, and hyper‑parameter sweeps are logged to MLflow, and the best model is packaged as a SageMaker endpoint using Docker.

## Architecture Overview

```
+-------------------+      +-------------------+      +-------------------+
|  Sensor Ingest    | ---> |  Airflow DAG      | ---> |  Feature Store    |
|  (S3 bucket)      |      |  (PythonOperator) |      |  (Parquet on S3) |
+-------------------+      +-------------------+      +-------------------+
                                 |                               |
                                 v                               v
                        +-------------------+            +-------------------+
                        |  Training Script  |            |  Inference Service |
                        |  (PyTorch + MLflow) |          |  (SageMaker + Docker) |
                        +-------------------+            +-------------------+
```

* **Airflow** runs every 24 h, orchestrating ETL and model retraining.
* **MLflow** tracks experiment parameters, metrics (RMSE, MAE) and stores model artifacts.
* **Docker** builds a reproducible image (`Dockerfile`) used both locally and in SageMaker.
* **AWS SageMaker** hosts the model behind a REST endpoint for real‑time predictions.

## Quick Start

1. **Prerequisites** – Python 3.10+, Docker, an AWS account with SageMaker permissions, and an Airflow instance (local or MWAA).
2. **Clone & install**
   ```bash
   git clone https://github.com/example/assembly-maintenance-forecast.git
   cd assembly-maintenance-forecast
   pip install -r requirements.txt
   ```
3. **Configure environment variables** (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET`).
4. **Run Airflow locally**
   ```bash
   airflow db init
   airflow users create --username admin --firstname Priya --lastname Raman --role Admin --email priya@example.com
   airflow webserver &
   airflow scheduler &
   ```
5. **Trigger a training run**
   ```bash
   python src/train_lstm.py --run-name "daily-retrain-$(date +%F)"
   ```
6. **Deploy to SageMaker** (Docker image is built automatically by the training script).

## Results

* Mean Time Between Failures (MTBF) increased **27 %** after three months of production.
* Annual maintenance cost dropped by **$1.2 M**.
* Model inference latency on SageMaker is ~45 ms per request.

---

For detailed design docs, see `docs/architecture.md`. Feel free to open issues or PRs.
