# Real‑estate Market Heatmap (realestate-heatmap)

**Project Overview**

This repository contains the data pipeline and Tableau integration code for the *Real‑estate Market Heatmap* built for a fast‑growing prop‑tech startup in 2021. Investors needed a geographic view of median listing prices and inventory levels across metropolitan regions to prioritize acquisition targets. The solution pulls daily MLS listings from a BigQuery table, enriches them with US Census demographic layers, and outputs a GeoJSON file that Tableau Desktop consumes as a spatial data source.

**Architecture**

1. **Data extraction** – `extract_listings.py` runs a parameterised BigQuery SQL query (via `google-cloud-bigquery`) to fetch the latest MLS data (≈ 1.2 M rows) into a Pandas DataFrame.
2. **Geospatial processing** – `process_heatmap.py` merges the listings with census tract shapefiles using GeoPandas, calculates median price and inventory per tract, and writes a simplified GeoJSON (`heatmap.geojson`).
3. **Tableau publishing** – `publish_to_tableau.py` uses Tableau’s REST API (`tableauhyperapi`) to replace the data source in an existing workbook, enabling analysts to refresh the heatmap with a single click.

**Setup**

```bash
# Clone the repo
git clone https://github.com/example/realestate-heatmap.git
cd realestate-heatmap

# Create a virtual environment and install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Set the following environment variables before running the scripts:
- `GOOGLE_APPLICATION_CREDENTIALS` – path to a service‑account JSON for BigQuery access.
- `TABLEAU_SITE_ID`, `TABLEAU_PROJECT_ID`, `TABLEAU_TOKEN_NAME`, `TABLEAU_TOKEN_SECRET` – Tableau Server credentials.

**Running the pipeline**

```bash
python extract_listings.py --date 2021-09-30
python process_heatmap.py --date 2021-09-30
python publish_to_tableau.py --workbook-id abc123
```

The heatmap was deployed in September 2021 and contributed to a **30 % increase in investor leads** and a **25 % reduction in deal cycle time**.

---

*Mariana Costa – Data Analyst*
