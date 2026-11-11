# Clinical Notes Summarizer

**Project**: Clinical Notes Summarizer (repo: `clinical-notes-summarizer`)
**Client**: Large healthcare enterprise
**Duration**: 10 weeks (Jan 2020 – Mar 2020)
**Role**: Lead AI Engineer (Priya Raman)

## Overview
Physicians were spending an average of 12 minutes per patient chart reading dense free‑text notes. The goal was to cut that time by at least 50 % while preserving clinical fidelity. We built an end‑to‑end abstractive summarization service using a fine‑tuned **BART‑large** model from Hugging Face, wrapped in **FastAPI**, containerised with **Docker**, and deployed to **AWS SageMaker**. Model lifecycle (training, validation, promotion) is tracked with **MLflow**, and a lightweight CI/CD pipeline (GitHub Actions → SageMaker endpoint) automates reproducible releases.

## Architecture
```
+----------------+      +----------------+      +-----------------+
|  Data Ingest   | ---> |   Preprocess   | ---> |  Model Service  |
|  (S3 CSV/JSON) |      |  (tokenizer)   |      |  (FastAPI)      |
+----------------+      +----------------+      +-----------------+
        |                         |                     |
        v                         v                     v
   SageMaker          SageMaker Training Job   SageMaker Endpoint
   (Batch)                (PyTorch)                (HTTPS)
```
* **Training** – PyTorch + Transformers on a SageMaker `ml.p3.2xlarge` instance. Training script logs metrics (loss, ROUGE‑L) to MLflow.
* **Inference** – FastAPI container receives a JSON payload `{"note": "..."}` and returns `{"summary": "..."}`. The container runs on a SageMaker multi‑model endpoint with auto‑scaling.
* **MLOps** – GitHub Actions triggers `mlflow run` on each PR; successful runs push a new model version to the SageMaker model registry and update the endpoint.

## Results
* Average physician reading time reduced from **12 min** to **4.5 min** (‑62 %).
* Summaries achieved **ROUGE‑L = 0.71** on a held‑out validation set.
* Model version turnover: 4 releases in 10 weeks, each traceable via MLflow UI.

## Getting Started
```bash
# Clone repo
git clone https://github.com/example/clinical-notes-summarizer.git
cd clinical-notes-summarizer

# Build Docker image
docker build -t notes-summarizer .

# Run locally (requires CUDA for faster inference)
docker run -p 8000:8000 notes-summarizer
```
The API is documented at `http://localhost:8000/docs`.

---
*All code is provided for illustration; production deployments used IAM‑restricted SageMaker roles and VPC endpoints.*
