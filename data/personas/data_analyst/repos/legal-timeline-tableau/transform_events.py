import os
import pandas as pd
from snowflake.connector import connect
from tableauhyperapi import HyperProcess, Connection, TableDefinition, SqlType, Inserter

SF_ACCOUNT = os.getenv('SNOWFLAKE_ACCOUNT')
SF_USER = os.getenv('SNOWFLAKE_USER')
SF_PASSWORD = os.getenv('SNOWFLAKE_PASSWORD')
SF_WAREHOUSE = os.getenv('SNOWFLAKE_WAREHOUSE', 'ANALYTICS_WH')
SF_DATABASE = os.getenv('SNOWFLAKE_DATABASE', 'LEGAL_DB')
SF_SCHEMA = os.getenv('SNOWFLAKE_SCHEMA', 'TRANSFORM')

HYPER_PATH = "case_events.hyper"


def get_snowflake_connection():
    return connect(
        user=SF_USER,
        password=SF_PASSWORD,
        account=SF_ACCOUNT,
        warehouse=SF_WAREHOUSE,
        database=SF_DATABASE,
        schema=SF_SCHEMA,
    )

def load_staging():
    sql = "SELECT * FROM stg_case_events"
    with get_snowflake_connection() as conn:
        df = pd.read_sql(sql, conn)
    return df

def aggregate_events(df: pd.DataFrame) -> pd.DataFrame:
    # Calculate days since case opened for each event
    df['case_open_date'] = df.groupby('case_id')['event_timestamp'].transform('min')
    df['days_since_open'] = (df['event_timestamp'] - df['case_open_date']).dt.days
    # Keep needed columns
    fact = df[['case_id', 'event_type', 'event_timestamp', 'jurisdiction', 'attorney_id', 'days_since_open']]
    return fact

def write_fact_to_snowflake(fact_df: pd.DataFrame):
    with get_snowflake_connection() as conn:
        fact_df.to_sql('case_events_fact', conn, if_exists='overwrite', index=False)


def create_hyper_extract(df: pd.DataFrame):
    table = TableDefinition(
        table_name="Extract.CaseEvents",
        columns=[
            TableDefinition.Column("case_id", SqlType.text()),
            TableDefinition.Column("event_type", SqlType.text()),
            TableDefinition.Column("event_timestamp", SqlType.timestamp()),
            TableDefinition.Column("jurisdiction", SqlType.text()),
            TableDefinition.Column("attorney_id", SqlType.text()),
            TableDefinition.Column("days_since_open", SqlType.int()),
        ],
    )
    with HyperProcess() as hyper:
        with Connection(endpoint=hyper.endpoint, database=HYPER_PATH, create_mode=Connection.CreateMode.CREATE_AND_REPLACE) as connection:
            connection.catalog.create_table(table)
            with Inserter(connection, table) as inserter:
                inserter.add_rows(df.itertuples(index=False, name=None))
                inserter.execute()
    print(f"Hyper extract written to {HYPER_PATH}")

if __name__ == "__main__":
    staging_df = load_staging()
    fact_df = aggregate_events(staging_df)
    write_fact_to_snowflake(fact_df)
    create_hyper_extract(fact_df)
    print(f"Transformed {len(fact_df)} fact rows")
