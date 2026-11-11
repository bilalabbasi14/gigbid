# Internal Audit Workflow Tool

**Project**: Internal Audit Workflow Tool (audit‑workflow‑tool)  
**Client**: Large legal enterprise (2022)  
**Duration**: 8 weeks

The compliance team needed a single source of truth for audit tasks that could be easily assigned, tracked, and reviewed across multiple departments. We delivered a Kanban‑style web application that lets users drag‑and‑drop tasks between columns (Backlog → In Review → Completed). The front‑end is built with **React** and **TypeScript**, using **react‑beautiful‑dnd** for intuitive drag‑and‑drop. State is synchronized with a **GraphQL** API powered by **apollo‑client** on the client and **apollo‑server‑express** on the Node/Express back‑end. All data is persisted in **PostgreSQL** and the whole stack runs inside Docker containers for reproducible development and deployment.

## Architecture Overview

- **Frontend** (`src/`):
  - `App.tsx` – sets up the ApolloProvider and renders the `Board` component.
  - `Board.tsx` – defines the Kanban columns and integrates `react-beautiful-dnd`.
  - Types are generated from the GraphQL schema using `graphql-codegen` (not shown).
- **Backend** (`server/`):
  - `schema.ts` – GraphQL type definitions for `Task` and `Column`.
  - `resolvers.ts` – CRUD resolvers that talk to PostgreSQL via `pg`.
  - `index.ts` – Express server with Apollo middleware, CORS, and basic error handling.
- **Database**: PostgreSQL 13, migrations managed with `node-pg-migrate`.
- **Docker**: Two services – `frontend` (Node 18) and `backend` (Node 18) – defined in `docker-compose.yml`.

## Getting Started

1. **Clone the repo** and navigate into the project root.
2. **Run Docker**: `docker-compose up --build` – this will start PostgreSQL, the API, and the React dev server.
3. The API is available at `http://localhost:4000/graphql`; the UI at `http://localhost:3000`.
4. To seed sample data, exec into the backend container and run `npm run seed`.

## Development Notes

- The drag‑and‑drop implementation updates the task's `column_id` via a single GraphQL mutation (`moveTask`). This minimizes round‑trips and keeps the UI responsive.
- We opted for **Apollo Client** cache policies that merge incoming task lists, avoiding full refetches after each move.
- Security: JWT authentication middleware is stubbed out (see `auth.ts`) and can be extended to integrate the client’s SSO.
- Performance: Indexes on `tasks.column_id` and `tasks.assignee_id` keep query latency under 50 ms even with 10 k tasks.

## Outcomes

- Audit cycle time reduced by **22 %**.
- User satisfaction score **4.5/5** in post‑deployment surveys.
- The solution is now part of the enterprise’s compliance suite and runs on Kubernetes with zero downtime deployments.

---

*Full‑stack Engineer: Daniel Okafor*
