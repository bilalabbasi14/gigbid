import argparse
import pathlib
import pandas as pd
import tableauserverclient as TSC

def dataframe_to_hyper(df: pd.DataFrame, hyper_path: pathlib.Path):
    # Minimal hyper creation using Tableau's Hyper API (installed via tableauhyperapi)
    from tableauhyperapi import HyperProcess, Connection, TableDefinition, SqlType, Inserter, CreateMode
    table = TableDefinition(
        table_name="Extract.CLV_Segments",
        columns=[
            TableDefinition.Column("customer_id", SqlType.text()),
            TableDefinition.Column("recency", SqlType.int()),
            TableDefinition.Column("frequency", SqlType.int()),
            TableDefinition.Column("monetary", SqlType.double()),
            TableDefinition.Column("clv", SqlType.double()),
            TableDefinition.Column("segment", SqlType.text()),
        ],
    )
    with HyperProcess() as hyper:
        with Connection(endpoint=hyper.endpoint, database=hyper_path, create_mode=CreateMode.CREATE_AND_REPLACE) as connection:
            connection.catalog.create_table(table)
            with Inserter(connection, table) as inserter:
                inserter.add_rows(df.itertuples(index=False, name=None))
                inserter.execute()

def publish_to_tableau(hyper_path: pathlib.Path, project_name: str, tableau_auth: TSC.PersonalAccessTokenAuth):
    server = TSC.Server(tableau_auth.server_url, use_server_version=True)
    with server.auth.sign_in(tableau_auth):
        all_projects, _ = server.projects.get()
        project = next(p for p in all_projects if p.name == project_name)
        new_ds = TSC.DatasourceItem(project_id=project.id, name="CLV_Segments")
        server.datasources.publish(new_ds, str(hyper_path), mode=TSC.Server.PublishMode.Overwrite)
        print(f"Datasource published to project '{project_name}'")

def main():
    parser = argparse.ArgumentParser(description='Publish CLV segments to Tableau Server')
    parser.add_argument('--extract', type=pathlib.Path, required=True, help='Path to processed CLV parquet')
    parser.add_argument('--project', type=str, required=True, help='Tableau project name')
    args = parser.parse_args()

    df = pd.read_parquet(args.extract)
    hyper_path = args.extract.with_suffix('.hyper')
    dataframe_to_hyper(df, hyper_path)

    tableau_auth = TSC.PersonalAccessTokenAuth(
        token_name=os.getenv('TABLEAU_TOKEN_NAME'),
        personal_access_token=os.getenv('TABLEAU_TOKEN_VALUE'),
        site_id=os.getenv('TABLEAU_SITE')
    )
    tableau_auth.server_url = os.getenv('TABLEAU_SERVER_URL', 'https://tableau.mycompany.com')
    publish_to_tableau(hyper_path, args.project, tableau_auth)

if __name__ == '__main__':
    main()
