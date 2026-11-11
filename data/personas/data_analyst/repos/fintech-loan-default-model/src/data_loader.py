import os
import pandas as pd
from snowflake.connector import connect

FEATURE_COLUMNS = [
    'credit_score', 'dti_ratio', 'loan_amount', 'interest_rate', 'term_months',
    'monthly_income', 'employment_years', 'num_open_accounts', 'avg_account_age',
    'utilization_rate', 'payment_history_score', 'debt_to_asset_ratio',
    'net_worth', 'cash_flow_positive_months', 'sector_risk_index', 'geographic_risk',
    'collateral_value', 'lender_spread', 'application_channel', 'prior_default_flag',
    'inquiry_count_12mo', 'balance_sheet_liabilities', 'equity_buffer', 'cash_reserve_months',
    'business_age_years'
]

def get_snowflake_connection():
    """
    Establishes a secure connection to the Snowflake data warehouse.
    Credentials are pulled from environment variables to avoid hardcoding.
    """
    return connect(
        user=os.getenv('SNOWFLAKE_USER'),
        password=os.getenv('SNOWFLAKE_PASSWORD'),
        account=os.getenv('SNOWFLAKE_ACCOUNT'),
        database=os.getenv('SNOWFLAKE_DB', 'FINTECH_PROD'),
        schema='ANALYTICS',
        warehouse='COMPUTE_WH',
        timeout=300
    )

def extract_loan_data():
    """
    Retrieves historical loan performance data from Snowflake.
    Filters for loans originated in the last 3 years to ensure data recency.
    """
    query = """
    SELECT 
        loan_id,
        applicant_id,
        default_6mo AS target,
        credit_score,
        dti_ratio,
        loan_amount,
        interest_rate,
        term_months,
        monthly_income,
        employment_years,
        num_open_accounts,
        avg_account_age,
        utilization_rate,
        payment_history_score,
        debt_to_asset_ratio,
        net_worth,
        cash_flow_positive_months,
        sector_risk_index,
        geographic_risk,
        collateral_value,
        lender_spread,
        application_channel,
        prior_default_flag,
        inquiry_count_12mo,
        balance_sheet_liabilities,
        equity_buffer,
        cash_reserve_months,
        business_age_years
    FROM finance.loan_applications
    WHERE origin_date >= DATEADD(year, -3, CURRENT_DATE)
    """
    
    conn = get_snowflake_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        df = pd.DataFrame(cursor.fetchall(), columns=[desc[0] for desc in cursor.description])
        return df
    finally:
        conn.close()

def preprocess_data(df):
    """
    Cleans and transforms raw data for model training.
    Handles missing values and encodes categorical variables.
    """
    df = df.copy()
    
    # Drop rows with missing target variable
    df = df.dropna(subset=['target'])
    
    # Impute numerical missing values with median
    num_cols = df.select_dtypes(include=['number']).columns
    for col in num_cols:
        if col != 'target':
            median_val = df[col].median()
            df[col] = df[col].fillna(median_val)
    
    # Encode categorical variables
    categorical_cols = ['application_channel', 'geographic_risk']
    for col in categorical_cols:
        if col in df.columns:
            df[col] = pd.get_dummies(df[col], prefix=col, drop_first=True)
    
    # Ensure all expected feature columns are present
    for col in FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = 0
            print(f"Warning: {col} not found in dataset, filled with 0.")
    
    return df
