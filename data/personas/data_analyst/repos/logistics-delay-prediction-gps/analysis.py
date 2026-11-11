import pandas as pd
from scipy import stats
import numpy as np

class DelayPredictor:
    def __init__(self, data: pd.DataFrame):
        self.data = data
        self.threshold = None

    def compute_risk_score(self):
        traffic_corr = self.data['traffic_density_score'].corr(self.data['delay_minutes'])
        weather_corr = self.data['weather_condition'].corr(self.data['delay_minutes'])
        weights = {'traffic': abs(traffic_corr), 'weather': abs(weather_corr)}
        total_weight = sum(weights.values())
        
        self.data['risk_score'] = (
            (self.data['traffic_density_score'] * weights['traffic'] / total_weight) +
            (self.data['weather_condition'] * weights['weather'] / total_weight)
        )
        self.threshold = self.data['risk_score'].quantile(0.85)
        return self.data

    def identify_high_risk(self):
        if self.threshold is None:
            self.compute_risk_score()
        return self.data[self.data['risk_score'] > self.threshold]

    def statistical_significance(self):
        delayed = self.data[self.data['delay_minutes'] > 15]['traffic_density_score']
        on_time = self.data[self.data['delay_minutes'] <= 15]['traffic_density_score']
        t_stat, p_value = stats.ttest_ind(delayed, on_time, equal_var=False)
        return {'t_statistic': t_stat, 'p_value': p_value, 'significant': p_value < 0.05}

if __name__ == "__main__":
    sample_data = pd.DataFrame({
        'traffic_density_score': np.random.uniform(0, 1, 1000),
        'weather_condition': np.random.uniform(0, 1, 1000),
        'delay_minutes': np.random.exponential(10, 1000)
    })
    predictor = DelayPredictor(sample_data)
    predictor.compute_risk_score()
    print(predictor.statistical_significance())
