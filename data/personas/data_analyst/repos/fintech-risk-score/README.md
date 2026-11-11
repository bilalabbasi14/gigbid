# Loan Risk Scoring System (fintech-risk-score)

**Project Overview**

In early 2022 the client, a large fintech lender, was struggling with manual loan risk assessments that caused decision delays (up to 48 hours) and inconsistent approval criteria across underwriting teams. Over a 10‑week engagement I designed and delivered an automated risk scoring pipeline that runs directly inside Snowflake using Python UDFs, integrates with existing SQL data marts, and is continuously validated through A/B testing on a pilot cohort.

**Architecture**

1. **Data Ingestion** – Raw application data lives in Snowflake tables (`loans_raw`, `customers`, `transactions`). A nightly dbt model (`models/loan_features.sql`) materialises a feature view (`loan_features_vw`) that joins these sources and performs basic cleaning.
2. **Scoring UDF** – The core model is a scikit‑learn GradientBoostingClassifier trained offline (see `train_model.py`). The trained model is serialized with `joblib` and uploaded to a Snowflake stage. A Python UDF (`score_loan`) defined in `udf/score_loan.sql` loads the model from the stage and returns a risk score for each loan row.
3. **A/B Test Framework** – `ab_test.py` splits incoming loan applications into control (legacy manual scoring) and treatment (UDF score) groups using a deterministic hash on `loan_id`. Results are stored in `loan_ab_results` for downstream analysis.
4. **Monitoring** – A simple Power BI dashboard (outside the repo) queries `loan_ab_results` to track decision latency and approval consistency. The Python script `evaluate_metrics.py` reproduces the key KPI calculations.

**Key Decisions & Trade‑offs**

- **Snowflake Python UDFs** were chosen to keep scoring latency low (sub‑second) and avoid data movement, at the cost of a 30 % larger warehouse credit consumption during peak hours.
- **GradientBoostingClassifier** provided the best ROC‑AUC (0.87) on a 70/30 train‑test split versus a LogisticRegression baseline (0.81).
- **A/B testing** was limited to a 5 % pilot cohort to mitigate risk while still delivering statistically significant results (p < 0.01) after 4 weeks.

**Results**

- Decision time reduced from an average of 48 h to 5 h.
- Approval consistency (measured as variance in risk score across underwriters) improved by 30 %.
- The solution is production‑ready and has been handed over to the client’s data engineering team for ongoing model retraining.

**How to Run**

1. Install dependencies from `requirements.txt`.
2. Configure Snowflake credentials in `.env` (see `.env.example`).
3. Execute `python train_model.py` to generate `model.joblib` and upload it to Snowflake.
4. Run `python ab_test.py` to start the pilot split, then `python evaluate_metrics.py` to view KPI reports.

---
*Mariana Costa – Data Analyst (SQL, Python, dbt, Snowflake)*
