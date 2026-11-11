import os
import pandas as pd
import snowflake.connector
from statsmodels.stats.proportion import proportion_confint

ctx = snowflake.connector.connect(
    user=os.getenv('SF_USER'),
    password=os.getenv('SF_PASSWORD'),
    account=os.getenv('SF_ACCOUNT'),
    warehouse='COMPUTE_WH',
    database='FINTECH_DB',
    schema='PUBLIC'
)

# Load AB results with decision times and approval flags
sql = """
SELECT group, decision_time_minutes, approved
FROM loan_ab_results
WHERE assigned_at >= DATEADD('day', -30, CURRENT_TIMESTAMP())
"""
df = pd.read_sql(sql, ctx)
ctx.close()

# KPI 1: average decision time reduction
avg_time = df.groupby('group')['decision_time_minutes'].mean()
print('Avg decision time (minutes):')
print(avg_time)

# KPI 2: approval consistency (proportion approved)
summary = df.groupby('group')['approved'].agg(['sum', 'count'])
summary['rate'] = summary['sum'] / summary['count']
summary['ci_low'], summary['ci_high'] = zip(*summary.apply(
    lambda r: proportion_confint(r['sum'], r['count'], method='wilson'), axis=1))
print('\nApproval rates with 95% CI:')
print(summary[['rate', 'ci_low', 'ci_high']])
