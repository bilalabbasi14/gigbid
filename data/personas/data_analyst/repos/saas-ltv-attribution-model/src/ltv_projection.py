import pandas as pd
import numpy as np
from typing import List

def project_ltv(
    cohort_data: pd.DataFrame,
    months: int = 24,
    growth_rate: float = 0.0
) -> pd.DataFrame:
    """
    Projects Lifetime Value (LTV) based on historical cohort retention curves.
    Uses a linear extrapolation for months beyond observed data.
    
    Parameters:
    - cohort_data: DataFrame with columns ['cohort_month', 'month_offset', 'avg_revenue_per_user']
    - months: Number of months to project into the future
    - growth_rate: Monthly growth rate for revenue per user
    """
    if cohort_data.empty:
        return pd.DataFrame()

    # Pivot data to have months as columns for easier vectorized operations
    pivot = cohort_data.pivot(index='cohort_month', columns='month_offset', values='avg_revenue_per_user')
    
    # Calculate average retention curve across all cohorts
    avg_curve = pivot.mean(axis=0).sort_index()
    
    # Extend the curve for projection if necessary
    if len(avg_curve) < months:
        last_value = avg_curve.iloc[-1]
        indices = range(len(avg_curve), months)
        extension = [last_value * (1 + growth_rate) ** i for i in indices]
        avg_curve = pd.concat([avg_curve, pd.Series(extension, index=indices)])

    # Calculate cumulative LTV
    ltv_series = avg_curve.cumsum()
    
    result = pd.DataFrame({
        'month': ltv_series.index,
        'avg_revenue_per_user': ltv_series.values,
        'cumulative_ltv': ltv_series.cumsum().values
    })
    
    return result

def calculate_roas(
    revenue_df: pd.DataFrame,
    spend_df: pd.DataFrame,
    channel: str
) -> float:
    """
    Calculates Return on Ad Spend (ROAS) for a specific channel.
    """
    total_revenue = revenue_df[revenue_df['channel'] == channel]['attributed_revenue'].sum()
    total_spend = spend_df[spend_df['channel'] == channel]['ad_spend'].sum()
    
    if total_spend == 0:
        return 0.0
    
    return total_revenue / total_spend

def identify_overallocated_channels(
    roas_data: pd.DataFrame,
    threshold: float = 1.5
) -> List[str]:
    """
    Identifies channels where ROAS is significantly below the threshold,
    indicating potential over-allocation of budget.
    """
    low_performing = roas_data[roas_data['roas'] < threshold]
    return low_performing['channel'].tolist()

if __name__ == "__main__":
    # Mock data for testing
    mock_cohorts = pd.DataFrame({
        'cohort_month': ['2024-01', '2024-01', '2024-02', '2024-02'],
        'month_offset': [0, 1, 0, 1],
        'avg_revenue_per_user': [100, 50, 105, 52]
    })
    
    ltv = project_ltv(mock_cohorts, months=6)
    print(ltv.to_string())
