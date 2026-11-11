# Production Line KPI Dashboard (factory‑kpi-dashboard)

**Overview**

This repository contains the core of a real‑time KPI dashboard built for a large manufacturing client in 2022. The system aggregates high‑frequency sensor readings from production equipment, stores them in PostgreSQL, and exposes a GraphQL API that powers a React/TypeScript front‑end with Recharts visualizations. The backend runs on Node.js/Express and uses `apollo-server-express` for the GraphQL layer. Docker is used for local development and CI pipelines.

**Architecture**

- **PostgreSQL** stores raw sensor events (`sensor_events` table) and pre‑computed aggregates (`equipment_kpis`).
- **Node.js (v18)** with **Express** hosts the GraphQL endpoint at `/graphql`. The schema is defined in `src/schema.ts` and resolvers in `src/resolvers.ts`.
- **Apollo Client** on the front‑end queries the API for KPI series (through `useKPIQuery`) and renders line and gauge charts with **Recharts**.
- **Docker Compose** spins up `db` (PostgreSQL 13) and `api` containers. The API container rebuilds on source changes using `nodemon`.

**Setup**

1. Install Docker Desktop.
2. Clone the repo and run `docker compose up --build`.
3. The API will be reachable at `http://localhost:4000/graphql`.
4. Run `npm run seed` to generate synthetic sensor data (10 000 rows) for demo purposes.
5. Open `http://localhost:3000` (the separate front‑end repo) to view the dashboard.

**Key Design Decisions**

- **GraphQL** was chosen over REST to let the UI request exactly the KPI series it needs, reducing over‑fetching.
- Aggregations are performed in SQL (`GROUP BY` and window functions) to leverage PostgreSQL’s query planner rather than pulling raw events into Node.
- **Recharts** provides declarative chart components with good TypeScript support and small bundle size.
- The Docker setup isolates the database and API, simplifying CI testing and ensuring reproducible environments.

**Results**

- Identified bottlenecks that saved **$120 K** annually.
- Achieved **85 %** adoption among shift leads within the first month.
- Response times for KPI queries stay under **120 ms** on average.

---

*Backend Engineer – Daniel Okafor*
