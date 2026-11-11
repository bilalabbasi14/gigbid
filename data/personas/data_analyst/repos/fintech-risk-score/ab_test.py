import os
import hashlib
import pandas as pd
import snowflake.connector

# Connect to Snowflake
ctx = snowflake.connector.connect(
    user=os.getenv('SF_USER'),
    password=os.getenv('SF_PASSWORD'),
    account=os.getenv('SF_ACCOUNT'),
    warehouse='COMPUTE_WH',
    database='FINTECH_DB',
    schema='PUBLIC'
)

# Pull new loan applications (last hour)
sql = """
SELECT loan_id, applicant_id, request_amount, loan_features_vw.*
FROM loan_features_vw
WHERE created_at >= DATEADD('hour', -1, CURRENT_TIMESTAMP())
"""
loans = pd.read_sql(sql, ctx)

# Deterministic split: 5% treatment, 95% control

def assign_group(loan_id: str) -> str:
    h = hashlib.sha256(loan_id.encode()).hexdigest()
    return 'treatment' if int(h[:2], 16) % 100 < 5 else 'control'

loans['group'] = loans['loan_id'].apply(assign_group)

# Write assignments back to Snowflake for downstream processing
insert_sql = """
INSERT INTO loan_ab_results (loan_id, group, assigned_at)
VALUES (%s, %s, CURRENT_TIMESTAMP())
"""
cs = ctx.cursor()
for _, row in loans.iterrows():
    cs.execute(insert_sql, (row['loan_id'], row['group']))
cs.close()
ctx.close()
print(f"Processed {len(loans)} loans – {loans['group'].value_counts().to_dict()}")
