# ecom-clv-segmentation

**Project overview**

This repository contains the data pipeline and visualisation artefacts built for a fast‑growing e‑commerce startup in 2024. The goal was to replace blanket marketing campaigns with customer‑specific offers by quantifying each shopper’s **Customer Lifetime Value (CLV)** and grouping them into actionable segments.

**Architecture**

1. **Data extraction** – A scheduled Airflow DAG (not included) runs a BigQuery export query and writes the raw transaction table to `data/raw_transactions.parquet`.
2. **Transformation & CLV calculation** – `src/clv_engine.py` reads the parquet file, enriches it with recency‑frequency‑monetary (RFM) metrics using **pandas** and **numpy**, applies a 12‑month discount factor, and writes the resulting dataframe to `data/processed/clv_segments.parquet`.
3. **Export to Tableau** – `src/tableau_publisher.py` uses the **Tableau Server Client (TSC)** library to publish the processed parquet as an extract (`clv_segments.hyper`) to a Tableau Server project named *E‑Commerce Analytics*.
4. **Dashboard** – A Tableau workbook (`dashboard/CLV_Segmentation.twbx`) consumes the extract and visualises the five segments (High‑Value, Loyal, New, At‑Risk, Churned) with KPI cards and a funnel chart.

**Setup**

```bash
# Clone the repo
git clone https://github.com/example/ecom-clv-segmentation.git
cd ecom-clv-segmentation

# Create a virtual environment (Python 3.10+)
python -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables (example)
export BIGQUERY_PROJECT=my-gcp-project
export TABLEAU_SITE=default
export TABLEAU_TOKEN_NAME=clv_service_account
export TABLEAU_TOKEN_VALUE=xxxxxxxxxxxx
```

**Running the pipeline**

```bash
python -m src.clv_engine --input data/raw_transactions.parquet --output data/processed/clv_segments.parquet
python -m src.tableau_publisher --extract data/processed/clv_segments.parquet --project "E-Commerce Analytics"
```

The pipeline was built in six weeks, processed ~2.3 M rows per run, and enabled the marketing team to increase campaign ROI by **22 %** and lift average order value by **9 %**.
