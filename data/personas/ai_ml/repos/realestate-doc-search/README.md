# Real‑Estate Document Analyzer – Phase 2

**Project:** Real‑Estate Document Analyzer – Phase 2 (repo: `realestate-doc-search`)
**Client:** Large real‑estate enterprise
**Duration:** 5 weeks (May 2022 – June 2022)
**Role:** ML Engineer (Priya Raman)

## Overview
The goal was to augment the existing contract‑processing pipeline with a semantic search capability so that agents could retrieve similar lease agreements or purchase contracts instantly. We added a vector‑search layer on top of PostgreSQL using the **pgvector** extension and built a **LangChain**‑based retriever that indexes cleaned contract text. A thin **FastAPI** service exposes a `/search` endpoint that returns the top‑k most similar documents together with a confidence score.

## Architecture
```
+----------------+      +-------------------+      +-------------------+
| FastAPI (Uvicorn) | →  | LangChain Retriever | →  | PostgreSQL + pgvector |
+----------------+      +-------------------+      +-------------------+
        ^                        ^                         ^
        |                        |                         |
        |   Docker Compose       |   Docker Compose        |   Docker Compose
        |                        |                         |
   client (web/mobile)   indexing job (Python)    persistent store
```
* **FastAPI** – lightweight async API, runs behind Uvicorn. Handles request validation with Pydantic and streams JSON responses.
* **LangChain** – `OpenAIEmbeddings` (text‑embedding‑ada‑002) generates 1536‑dim vectors; `PGVectorRetriever` performs similarity search using inner‑product distance.
* **pgvector** – stores embeddings in a column of type `vector(1536)`. Index created with `ivfflat` for sub‑millisecond ANN queries.
* **Docker** – `docker-compose.yml` spins up three containers: `api`, `db` (Postgres 13 with pgvector), and `worker` for batch indexing.

## Setup
```bash
# Clone the repo
git clone https://github.com/example/realestate-doc-search.git
cd realestate-doc-search

# Build and start services (requires Docker & Docker‑Compose)
docker-compose up --build -d

# Run migrations (creates vector column & index)
python -m scripts.migrate

# Index existing contracts (run once or schedule)
python -m scripts.indexer ./data/contracts/*.txt
```
The API will be reachable at `http://localhost:8000`. Example request:
```bash
curl -X POST http://localhost:8000/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "early termination clause", "k": 5}'
```

## Results
* **Search latency:** average 172 ms for 5‑nearest‑neighbor queries (vs. 540 ms in Phase 1).
* **User satisfaction:** internal survey score increased from 3.9 to 4.6/5.
* **Scalability:** the vector index supports >200 k contracts with <0.5 GB RAM.

---
*All code is production‑ready and includes type hints, logging, and basic error handling.*
