import os
import glob
from pathlib import Path
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import PGVector
from tqdm import tqdm
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/documents")
embeddings = OpenAIEmbeddings(model="text-embedding-ada-002")
vector_store = PGVector(
    embedding_function=embeddings,
    collection_name="contracts",
    connection_string=DATABASE_URL,
)

def index_folder(folder_path: str):
    files = glob.glob(os.path.join(folder_path, "*.txt"))
    logger.info(f"Found {len(files)} contract files to index")
    for file_path in tqdm(files, desc="Indexing contracts"):
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        doc_id = Path(file_path).stem
        # Upsert document – LangChain will handle duplicate ids
        vector_store.add_texts(
            texts=[content],
            metadatas=[{"doc_id": doc_id}],
            ids=[doc_id],
        )
    logger.info("Indexing complete")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.indexer <folder>")
        sys.exit(1)
    index_folder(sys.argv[1])
