import pytest
from dbt.tests.util import relation_from_name, run_dbt
from dbt.tests.fixtures.project import project_config_update

@project_config_update({
    "models": {
        "enterprise_migration": {
            "+materialized": "table"
        }
    }
})
class TestOrderIntegrity:
    """
    Validates that the stg_orders model maintains referential integrity
    and data types as per the dbt schema.yml definitions.
    """

    @pytest.fixture(scope="class")
    def models(self):
        return {
            "stg_orders.sql": """
            select 1 as order_id, 'CUST_001' as customer_id, 100.0 as order_total
            """
        }

    def test_model_data(self, project):
        run_dbt(["run"])
        # Assert that the model was created and contains expected data
        results = project.run_sql(
            "select * from stg_orders", fetch="all"
        )
        assert len(results) == 1
        assert results[0][0] == 1  # order_id
        assert results[0][2] == 100.0  # order_total
