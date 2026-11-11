from langchain.vectorstores import PGVector
from langchain.embeddings import HuggingFaceEmbeddings
import os

# Connection string built from Docker env vars
connection_string = (
    f"postgresql://{os.getenv('POSTGRES_USER', 'postgres')}:{os.getenv('POSTGRES_PASSWORD', 'example')}@"
    f"{os.getenv('POSTGRES_HOST', 'db')}:5432/{os.getenv('POSTGRES_DB', 'contracts')}"
)

# Use the same tokenizer/embedding model as ingestion for consistency
embeddings = HuggingFaceEmbeddings(model_name='sentence-transformers/all-MiniLM-L6-v2')

vector_store = PGVector(
    embedding_function=embeddings,
    connection_string=connection_string,
    collection_name='clauses',
    distance_strategy='cosine'
)

def retrieve(query: str, k: int = 5):
    """Return top‑k clause IDs and texts most similar to the query."""
    docs = vector_store.max_marginal_relevance_search(query, k=k)
    return [(doc.metadata['clause_id'], doc.page_content) for doc in docs]
