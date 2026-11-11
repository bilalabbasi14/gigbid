import os
import pandas as pd
from snowflake.connector import connect

# Snowflake connection parameters from env
SF_ACCOUNT = os.getenv('SNOWFLAKE_ACCOUNT')
SF_USER = os.getenv('SNOWFLAKE_USER')
SF_PASSWORD = os.getenv('SNOWFLAKE_PASSWORD')
SF_WAREHOUSE = os.getenv('SNOWFLAKE_WAREHOUSE', 'ANALYTICS_WH')
SF_DATABASE = os.getenv('SNOWFLAKE_DATABASE', 'LEGAL_DB')
SF_SCHEMA = os.getenv('SNOWFLAKE_SCHEMA', 'RAW')

def get_snowflake_connection():
    return connect(
        user=SF_USER,
        password=SF_PASSWORD,
        account=SF_ACCOUNT,
        warehouse=SF_WAREHOUSE,
        database=SF_DATABASE,
        schema=SF_SCHEMA,
    )

def fetch_raw_events():
    sql = """
        SELECT case_id, event_type, event_timestamp, jurisdiction, attorney_id
        FROM raw_case_events
        WHERE event_timestamp >= DATEADD(day, -30, CURRENT_DATE())
    """
    with get_snowflake_connection() as conn:
        df = pd.read_sql(sql, conn)
    return df

def clean_events(df: pd.DataFrame) -> pd.DataFrame:
    # Standardize timestamps to UTC
    df['event_timestamp'] = pd.to_datetime(df['event_timestamp'], utc=True)
    # Remove duplicates
    df = df.drop_duplicates(subset=['case_id', 'event_type', 'event_timestamp'])
    # Normalize jurisdiction codes (e.g., "NY" -> "New York")
    jurisdiction_map = {
        'NY': 'New York',
        'CA': 'California',
        'TX': 'Texas',
    }
    df['jurisdiction'] = df['jurisdiction'].map(jurisdiction_map).fillna(df['jurisdiction'])
    return df

if __name__ == "__main__":
    raw_df = fetch_raw_events()
    clean_df = clean_events(raw_df)
    # Write cleaned data back to Snowflake staging table
    with get_snowflake_connection() as conn:
        clean_df.to_sql('stg_case_events', conn, if_exists='replace', index=False)
    print(f"Extracted and cleaned {len(clean_df)} rows")
