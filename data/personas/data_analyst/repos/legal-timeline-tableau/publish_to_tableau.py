import os
from tableau_api_lib import TableauServerConnection
from tableau_api_lib.utils.querying import get_projects_dataframe

HYPER_PATH = "case_events.hyper"
TABLEAU_SERVER = os.getenv('TABLEAU_SERVER')
TABLEAU_TOKEN_NAME = os.getenv('TABLEAU_TOKEN_NAME')
TABLEAU_TOKEN_VALUE = os.getenv('TABLEAU_TOKEN_VALUE')
PROJECT_NAME = "Legal Analytics"
DATASOURCE_NAME = "Case Events Extract"
WORKBOOK_NAME = "Legal Case Timeline"

connection = TableauServerConnection(
    server=TABLEAU_SERVER,
    personal_access_token_name=TABLEAU_TOKEN_NAME,
    personal_access_token_secret=TABLEAU_TOKEN_VALUE,
    site_id="",
)
connection.sign_in()

# Find the target project ID
projects_df = get_projects_dataframe(connection)
project_id = projects_df[projects_df.name == PROJECT_NAME].iloc[0].id

# Publish (or replace) the Hyper extract as a datasource
with open(HYPER_PATH, "rb") as f:
    connection.publish_datasource(
        datasource_file=f,
        datasource_name=DATASOURCE_NAME,
        project_id=project_id,
        overwrite=True,
    )
print(f"Datasource '{DATASOURCE_NAME}' published to project '{PROJECT_NAME}'.")

# Refresh the workbook to pick up the new datasource
workbooks = connection.query_workbooks()
wb_id = next(wb["id"] for wb in workbooks["workbooks"] if wb["name"] == WORKBOOK_NAME)
connection.refresh_workbook(wb_id)
print(f"Workbook '{WORKBOOK_NAME}' refreshed.")

connection.sign_out()
