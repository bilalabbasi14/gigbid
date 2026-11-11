import os
import argparse
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

CENSUS_SHAPEFILE = "data/census_tracts_2020.geojson"

def load_census():
    return gpd.read_file(CENSUS_SHAPEFILE).to_crs(epsg=4326)

def load_listings(parquet_path: str) -> pd.DataFrame:
    return pd.read_parquet(parquet_path)

def enrich(listings: pd.DataFrame, census_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    # Convert listings to GeoDataFrame
    geometry = [Point(xy) for xy in zip(listings.longitude, listings.latitude)]
    listings_gdf = gpd.GeoDataFrame(listings, geometry=geometry, crs="EPSG:4326")
    # Spatial join to assign tract ID
    joined = gpd.sjoin(listings_gdf, census_gdf, how="inner", predicate="within")
    # Aggregate per tract
    agg = joined.groupby("GEOID").agg(
        median_price=pd.NamedAgg(column="price", aggfunc="median"),
        inventory=pd.NamedAgg(column="listing_id", aggfunc="count"),
        geometry=pd.NamedAgg(column="geometry", aggfunc="first")
    ).reset_index()
    # Build final GeoDataFrame
    result = gpd.GeoDataFrame(agg, geometry="geometry", crs="EPSG:4326")
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process listings into a heatmap GeoJSON.")
    parser.add_argument("--date", required=True, help="Date of the listings parquet file")
    args = parser.parse_args()

    listings_path = os.path.join("data", f"listings_{args.date}.parquet")
    listings_df = load_listings(listings_path)
    census_gdf = load_census()
    heatmap_gdf = enrich(listings_df, census_gdf)

    output_path = os.path.join("output", f"heatmap_{args.date}.geojson")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    heatmap_gdf.to_file(output_path, driver="GeoJSON")
    print(f"Heatmap GeoJSON saved to {output_path}")
