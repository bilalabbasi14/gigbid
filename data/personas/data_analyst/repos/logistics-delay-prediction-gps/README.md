# Supply Chain Delay Prediction & Route Optimization

This repository contains the analytical pipeline used to predict delivery delays for a major logistics enterprise. The system ingests 3 years of historical GPS telemetry and delivery timestamps from Google BigQuery, processes them using pandas, and applies statistical modeling via scipy to flag high-risk shipments 24 hours in advance.

## Architecture

The pipeline is orchestrated by Apache Airflow. Daily scheduled DAGs trigger the `data_loader` to fetch raw event streams. The `analysis` module computes rolling statistics and identifies primary delay drivers based on traffic density and weather conditions. Finally, the `visualizer` generates executive dashboards using matplotlib to highlight on-time performance metrics.

## Setup

1. Clone the repository.
2. Install dependencies: `pip install -r requirements.txt`.
3. Set up your Airflow environment and configure BigQuery credentials via environment variables.
4. Deploy the DAGs to the scheduler.

## Key Components

- `data_loader.py`: Handles BigQuery extraction and pandas DataFrame transformation.
- `analysis.py`: Core statistical logic for risk scoring and delay attribution.
- `visualizer.py`: Generates predictive trend reports for dispatch teams.

## Outcomes

Implementation of this model reduced late deliveries by 18% and improved the overall on-time performance metric to 94% by enabling proactive route rerouting.
