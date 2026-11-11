import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import PGVector
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural language query")
    k: int = Field(5, ge=1, le=20, description="Number of results to return")

app = FastAPI(title="RealEstate Document Search API", version="0.1.0")

# DB connection – uses env vars from docker‑compose
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/documents")
engine = create_engine(DATABASE_URL)

# LangChain components – instantiated once at startup
embeddings = OpenAIEmbeddings(model="text-embedding-ada-002")
vector_store = PGVector(
    embedding_function=embeddings,
    collection_name="contracts",
    connection_string=DATABASE_URL,
)

@app.post("/search")
async def semantic_search(req: SearchRequest):
    try:
        docs = vector_store.max_marginal_relevance_search(
            query=req.query,
            k=req.k,
            fetch_k=req.k * 2,
        )
        results = [
            {"id": doc.metadata.get("doc_id"), "score": doc.score, "snippet": doc.page_content[:200]}
            for doc in docs
        ]
        return {"query": req.query, "results": results}
    except SQLAlchemyError as e:
        logger.exception("Database error during search")
        raise HTTPException(status_code=500, detail="Search service unavailable")
    except Exception as e:
        logger.exception("Unexpected error")
        raise HTTPException(status_code=400, detail=str(e))
