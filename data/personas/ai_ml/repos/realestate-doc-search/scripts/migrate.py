import os
from sqlalchemy import create_engine, text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/documents")
engine = create_engine(DATABASE_URL)

SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS contracts (
    id SERIAL PRIMARY KEY,
    doc_id TEXT UNIQUE,
    content TEXT NOT NULL,
    embedding VECTOR(1536)
);
-- ivfflat index for fast inner‑product search
CREATE INDEX IF NOT EXISTS idx_contracts_embedding ON contracts USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
"""

if __name__ == "__main__":
    with engine.begin() as conn:
        logger.info("Running migrations…")
        conn.execute(text(SQL))
        logger.info("Migrations applied successfully")
