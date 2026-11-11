import sqlalchemy
import pandas as pd
from sqlalchemy import create_engine
import os

class CaseDataLoader:
    def __init__(self, db_url=None):
        self.db_url = db_url or os.getenv("LEGAL_DB_URL")
        if not self.db_url:
            raise ValueError("Database URL not configured")
        self.engine = create_engine(self.db_url)
        
    def load_cases(self, limit=1000):
        query = """
        SELECT 
            case_id,
            title,
            summary,
            outcome,
            court_level,
            filing_date,
            primary_statute
        FROM legal_cases
        WHERE summary IS NOT NULL
        ORDER BY filing_date DESC
        LIMIT :limit
        """
        params = {"limit": limit}
        df = pd.read_sql(query, self.engine, params=params)
        return df

    def load_precedents(self, statute_code):
        query = """
        SELECT 
            case_id,
            title,
            summary,
            outcome
        FROM legal_cases
        WHERE primary_statute = :statute
        AND outcome IN ('win', 'loss', 'settlement')
        """
        params = {"statute": statute_code}
        df = pd.read_sql(query, self.engine, params=params)
        return df

    def save_predictions(self, predictions_df):
        try:
            predictions_df.to_sql(
                "case_predictions",
                self.engine,
                if_exists="append",
                index=False
            )
            return True
        except Exception as e:
            print(f"Failed to save predictions: {e}")
            return False
