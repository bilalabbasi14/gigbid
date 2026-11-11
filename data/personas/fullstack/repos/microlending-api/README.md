# Micro‑lending Platform API (microlending-api)

This repository contains the core backend service for a fintech micro‑lending startup built in **TypeScript** with **Node.js** and **Express**. The API handles the full loan lifecycle – from application submission, credit‑score caching, to disbursement via **Stripe Connect** and repayment tracking.

## Architecture Overview
- **Express** routes are grouped by domain (`/loans`, `/payments`).
- **TypeORM** provides a clean data‑access layer for PostgreSQL tables (`users`, `loans`, `repayments`).
- **ioredis** is used as a read‑through cache for external credit‑score lookups, dramatically reducing third‑party latency.
- **Stripe** SDK is integrated for creating connected accounts and issuing payouts to borrowers.
- **Docker** composes three containers: `api`, `postgres`, and `redis`. Environment variables are injected via a `.env` file (see `.env.example`).
- **Jest** test suite covers critical service logic (loan approval, payout creation) and runs in the CI pipeline.

## Setup
1. **Clone** the repo and `cd microlending-api`.
2. Create a PostgreSQL database and a Redis instance (Docker compose will spin them up locally).
3. Copy `.env.example` to `.env` and fill in the required secrets (`DB_URL`, `REDIS_URL`, `STRIPE_SECRET_KEY`).
4. Install dependencies: `npm ci`.
5. Build the TypeScript sources: `npm run build`.
6. Start the stack: `docker-compose up --build`.
7. The API will be reachable at `http://localhost:3000`.

## Key Endpoints
- `POST /loans` – submit a new loan application.
- `GET /loans/:id` – fetch loan status and repayment schedule.
- `POST /payments/payout` – trigger a Stripe Connect payout for approved loans.
- `GET /creditscore/:userId` – cached credit‑score lookup.

## Testing & Linting
- Run unit tests: `npm test`.
- Lint with ESLint: `npm run lint`.

## Performance & Security
- Redis caching cuts credit‑score lookup time from ~1.2 s to < 100 ms.
- All routes are protected by JWT middleware (not shown here) and use parameterized queries via TypeORM to prevent SQL injection.
- Stripe webhook verification ensures payouts are only recorded after successful transfer.

---
*Developed by Daniel Okafor, Backend Lead (13‑week sprint, 2023). Processed $3 M in loans within the first four months; average approval time reduced from 48 h to 6 h.*
