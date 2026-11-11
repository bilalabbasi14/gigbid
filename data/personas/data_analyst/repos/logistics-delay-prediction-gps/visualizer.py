import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

class PerformanceVisualizer:
    def __init__(self, data: pd.DataFrame):
        self.data = data
        self.fig, self.axes = plt.subplots(2, 1, figsize=(12, 8))

    def plot_delay_trends(self):
        daily_delays = self.data.groupby('scheduled_delivery_ts').agg({'delay_minutes': 'mean'})
        self.axes[0].plot(daily_delays.index, daily_delays['delay_minutes'], color='#FF5733')
        self.axes[0].set_title('Average Daily Delivery Delay (Minutes)')
        self.axes[0].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.setp(self.axes[0].get_xticklabels(), rotation=45)

    def plot_risk_distribution(self):
        self.axes[1].hist(self.data['risk_score'], bins=50, color='#3366CC', edgecolor='black')
        self.axes[1].axvline(self.data['risk_score'].quantile(0.85), color='red', linestyle='--', label='High Risk Threshold')
        self.axes[1].set_title('Shipment Risk Score Distribution')
        self.axes[1].legend()

    def save_report(self, filename='performance_report.png'):
        plt.tight_layout()
        plt.savefig(filename, dpi=150)
        print(f"Report saved to {filename}")

if __name__ == "__main__":
    mock_data = pd.DataFrame({
        'scheduled_delivery_ts': pd.date_range('2024-01-01', periods=100, freq='D'),
        'delay_minutes': [12.5, 8.2, 15.1, 9.8, 22.4],
        'risk_score': [0.45, 0.32, 0.88, 0.51, 0.92]
    })
    viz = PerformanceVisualizer(mock_data)
    viz.plot_delay_trends()
    viz.plot_risk_distribution()
    viz.save_report()
