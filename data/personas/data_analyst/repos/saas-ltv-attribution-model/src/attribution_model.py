import pandas as pd
import numpy as np
from datetime import datetime

class MultiTouchAttribution:
    def __init__(self, decay_rate=0.8):
        self.decay_rate = decay_rate

    def apply_time_decay(self, touchpoints: pd.DataFrame) -> pd.DataFrame:
        """
        Applies exponential time decay to touchpoints to determine credit weight.
        Touchpoints must be sorted by timestamp in descending order.
        """
        df = touchpoints.copy()
        if df.empty:
            return df

        df['days_ago'] = (datetime.now() - df['touch_date']).dt.days
        df['raw_weight'] = self.decay_rate ** df['days_ago']
        df['total_raw_weight'] = df['raw_weight'].sum()
        df['attribution_share'] = df['raw_weight'] / df['total_raw_weight']
        
        return df

    def attribute_revenue(self, events: pd.DataFrame, revenue: float) -> pd.DataFrame:
        """
        Distributes total revenue across touchpoints based on calculated attribution shares.
        """
        weighted = self.apply_time_decay(events)
        weighted['attributed_revenue'] = weighted['attribution_share'] * revenue
        
        # Select relevant columns for the final output
        result = weighted[['channel', 'touch_date', 'attribution_share', 'attributed_revenue']]
        return result

def calculate_cohort_retention(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates retention rates for subscription cohorts.
    Expects columns: cohort_month, period_offset, active_subscribers
    """
    df = df.copy()
    base = df[df['period_offset'] == 0].set_index('cohort_month')['active_subscribers']
    
    df['retention_rate'] = df.apply(
        lambda row: row['active_subscribers'] / base.get(row['cohort_month'], 1), axis=1
    )
    
    return df

if __name__ == "__main__":
    # Example usage with synthetic data structure
    sample_events = pd.DataFrame({
        'channel': ['Paid Search', 'Organic', 'Paid Search', 'Email'],
        'touch_date': [
            pd.Timestamp('2024-01-01'),
            pd.Timestamp('2024-01-05'),
            pd.Timestamp('2024-01-10'),
            pd.Timestamp('2024-01-15')
        ]
    })
    
    model = MultiTouchAttribution(decay_rate=0.9)
    results = model.attribute_revenue(sample_events, revenue=1000.0)
    print(results.to_string())
