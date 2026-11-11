import os
import argparse
from tableauhyperapi import HyperProcess, Connection, TableDefinition, SqlType, Inserter
from tableau_api_lib import TableauServerConnection
from tableau_api_lib.utils import querying

def get_tableau_connection() -> TableauServerConnection:
    return TableauServerConnection(
        server=os.getenv("TABLEAU_SERVER_URL"),
        api_version="3.13",
        site_id=os.getenv("TABLEAU_SITE_ID"),
        personal_access_token_name=os.getenv("TABLEAU_TOKEN_NAME"),
        personal_access_token_secret=os.getenv("TABLEAU_TOKEN_SECRET"),
    )

def replace_datasource(workbook_id: str, geojson_path: str):
    conn = get_tableau_connection()
    conn.sign_in()
    # Find the datasource ID linked to the workbook (simplified example)
    datasources = querying.get_datasources(conn)
    ds_id = next(ds["id"] for ds in datasources if ds["name"] == "Heatmap GeoJSON")
    # Publish new version of the datasource (as a Hyper extract for speed)
    with HyperProcess() as hyper:
        with Connection(endpoint=hyper.endpoint, database=geojson_path) as connection:
            # Assuming the GeoJSON has columns: GEOID, median_price, inventory, geometry
            # The Hyper API can ingest a CSV; here we convert on‑the‑fly for demo
            pass  # In production, convert GeoJSON to CSV and use Inserter
    # Update workbook to point to new datasource version
    conn.update_datasource(ds_id, workbook_id=workbook_id)
    conn.sign_out()
    print(f"Datasource {ds_id} refreshed for workbook {workbook_id}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish heatmap GeoJSON to Tableau.")
    parser.add_argument("--workbook-id", required=True, help="Target Tableau workbook ID")
    parser.add_argument("--date", required=True, help="Date suffix for the heatmap file")
    args = parser.parse_args()
    geojson_file = os.path.join("output", f"heatmap_{args.date}.geojson")
    replace_datasource(args.workbook_id, geojson_file)
