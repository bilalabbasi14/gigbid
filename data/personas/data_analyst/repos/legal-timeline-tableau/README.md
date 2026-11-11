# Legal Case Timeline Visualizer

**Project:** Legal case timeline visualizer (p09) – 2025

**Client:** Global law firm (enterprise) – partners needed a single source of truth for case milestones across 12 jurisdictions.

## Overview
The solution normalizes raw case event logs stored in Snowflake into a tidy fact table (`case_events_fact`) and then publishes an interactive Tableau workbook that lets users filter by jurisdiction, attorney, and case type. The data pipeline runs nightly, materializing a Tableau Hyper extract that powers a dashboard with a scrollable Gantt‑style timeline.

## Architecture
1. **Ingestion (Python)** – A scheduled Airflow DAG triggers `extract_events.py`. It connects to Snowflake via the `snowflake-connector-python` driver, pulls the raw `raw_case_events` table, and uses **pandas** to clean and enrich the data (date parsing, duplicate removal, jurisdiction standardization).
2. **Transformation (Python)** – `transform_events.py` aggregates events per case, calculates `days_since_open`, and writes the result back to Snowflake (`case_events_fact`). The script also creates a Tableau Hyper extract using **tableauhyperapi**.
3. **Publishing (Python)** – `publish_to_tableau.py` authenticates with Tableau Server using **tableau-api-lib** (Tableau Server Client) and replaces the existing data source in the `Legal Case Timeline` workbook.
4. **Dashboard (Tableau)** – The workbook consumes the Hyper extract, provides filter actions for jurisdiction and attorney, and visualizes milestones with a custom Gantt chart.

## Setup
```bash
# Clone the repo
git clone https://github.com/example/legal-timeline-tableau.git
cd legal-timeline-tableau

# Create a virtualenv and install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure environment variables (example)
export SNOWFLAKE_USER=... SNOWFLAKE_PASSWORD=...
export TABLEAU_SERVER=tableau.myfirm.com
export TABLEAU_TOKEN_NAME=etl_token
export TABLEAU_TOKEN_VALUE=...

# Run the pipeline manually (for testing)
python extract_events.py && python transform_events.py && python publish_to_tableau.py
```

## Testing & Validation
* Unit tests (`tests/`) cover schema validation and date handling (pytest, coverage > 85%).
* End‑to‑end validation scripts compare row counts between Snowflake and the Hyper extract.
* Performance: nightly run processes ~2.3 M rows in ~7 minutes on an m5.large EC2 instance.

## Results
* Time to case resolution shortened by **18 %**.
* Partner satisfaction score increased by **15 %** (survey Q4 2025).

---
*Mariana Costa – BI Analyst*
