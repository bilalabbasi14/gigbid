This repository contains the predictive modeling pipeline for the Loan Default Risk Scoring System deployed in 2023. The project addressed the lending team's need for a statistical model to predict 6-month default probabilities, replacing heuristic-based manual underwriting.

### Architecture
The data pipeline extracts 25 financial and behavioral variables from Snowflake using `snowflake-connector-python`. Data is processed with `pandas` to handle missing values and engineer interaction features. The core model is a regularized logistic regression implemented in `scikit-learn`, selected for interpretability requirements by the risk compliance team. Model diagnostics, including VIF analysis and residual plots, are generated using `statsmodels` to ensure statistical rigor.

### Setup
1. Create a virtual environment and install dependencies: `pip install -r requirements.txt`.
2. Configure environment variables: `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_ACCOUNT`, and `SNOWFLAKE_DB`.
3. Run the data extraction: `python src/data_loader.py`.
4. Train and evaluate the model: `python src/model_pipeline.py`.

### Validation
The model was validated via an A/B test comparing approval rates and loss ratios against the baseline manual process. The system maintained approval rate variance within 1.5% of the baseline while reducing bad debt by 8% year-over-year. Cross-validation scores and SHAP values are logged in the `artifacts/` directory for audit purposes.
