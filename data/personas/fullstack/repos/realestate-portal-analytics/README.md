# Property Listings Portal – Phase 3 (Analytics)

**Project Overview**

The real‑estate agency needed a lightweight analytics layer that could surface listing performance and user interaction metrics directly inside their existing property portal. Over a six‑week sprint in Q2 2023, I led the backend effort, designing a GraphQL micro‑service that ingests click and view events, aggregates them in Redis for near‑real‑time queries, and persists daily summaries to PostgreSQL for historical reporting. The service is containerised with Docker and runs alongside the agency’s existing Node/Express stack.

**Architecture**

- **API layer** – `apollo-server-express` provides a GraphQL endpoint (`/graphql`) that the front‑end consumes.
- **Event ingestion** – HTTP POST `/events` stores raw events in a Redis stream (`events:raw`). A background worker reads the stream, updates rolling counters in a Redis hash (`stats:listing:{id}`) and writes aggregated rows to PostgreSQL (`listing_daily_stats`).
- **Data store** – PostgreSQL holds immutable daily aggregates; Redis holds hot counters for sub‑second dashboard refreshes.
- **Docker** – `docker-compose.yml` spins up `analytics-service`, `redis`, and `postgres` containers, exposing only the GraphQL port (4000) to the portal.

**Key Decisions & Trade‑offs**

- Chose Redis hashes for per‑listing counters to avoid the latency of writing every event to Postgres. The trade‑off is eventual consistency; a daily batch job flushes the in‑memory totals to the relational store.
- Used `ioredis` over `redis` for its built‑in clustering support – future‑proofing as the agency scales.
- Opted for a thin GraphQL schema (only the queries needed by the dashboard) to keep the surface area small and improve response times.

**Running the Service**

```bash
# clone the repo
git clone https://github.com/example/realestate-portal-analytics.git
cd realestate-portal-analytics

# start dependencies
docker-compose up -d

# install deps and launch
npm install
npm run dev   # starts GraphQL server on http://localhost:4000/graphql
```

**Results**

- Agent dashboards were adopted by **90 %** of staff within the first month.
- Data‑driven pricing adjustments derived from the analytics increased the average sale price by **4 %**.

---

*Backend Lead: Daniel Okafor*
