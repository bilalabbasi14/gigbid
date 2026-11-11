# Sustainable Marketplace MVP (sustainable-marketplace-mvp)

**Overview**

This repository contains the core of a 12‑week MVP built for a green‑goods startup in 2020. The product is a server‑rendered Next.js storefront (React + TypeScript) with a custom Stripe checkout, backed by a Node/Express API that talks to PostgreSQL through Prisma. The whole stack is containerised with Docker and orchestrated via `docker‑compose`. The architecture mirrors a typical modern SaaS: a thin API layer for business logic, a statically‑typed front‑end for SEO, and a PostgreSQL data store for reliability.

**Key components**
- **frontend/** – Next.js app using `next‑auth` for email‑password login, `react‑query` for data fetching, and Tailwind CSS for styling.
- **api/** – Express server exposing `/products`, `/orders`, and Stripe webhook endpoints. Prisma ORM handles migrations and type‑safe queries.
- **docker-compose.yml** – Spins up three services: `web` (Next.js), `api` (Express), and `db` (PostgreSQL).
- **scripts/** – Helper scripts for seeding the DB and running migrations.

**Setup**
1. Install Docker Desktop.
2. Clone the repo and run `docker-compose up --build` – this builds the images, runs migrations, and seeds sample eco‑friendly products.
3. The frontend will be available at `http://localhost:3000` and the API at `http://localhost:4000`.
4. Stripe test keys are read from `.env.local` (sample provided). Use the Stripe dashboard to view test payments.

**Architecture notes**
- The Next.js pages are rendered server‑side for SEO, while client‑side interactions (cart, checkout) use `react‑query` to keep UI state in sync with the API.
- Authentication state is stored in an HTTP‑only cookie via `next‑auth`; the API validates the session token on each request.
- Prisma generates TypeScript types from the PostgreSQL schema, eliminating runtime query errors.
- Docker isolates the dev environment, making the deployment to AWS ECS a single `docker push` and task definition change.

**Metrics**
- Launched within the 12‑week deadline.
- First‑month revenue: **$45K**.
- Over **10,000** registered users after six months.

**Running tests**
```bash
# From the repo root
npm run test:api   # Jest tests for the Express layer
npm run test:web   # React Testing Library for components
```

**Future work**
- Add a GraphQL gateway for mobile clients.
- Implement subscription‑based recurring orders.
- Migrate static assets to S3 + CloudFront.

---
*Lead Full‑stack Engineer: Daniel Okafor*
