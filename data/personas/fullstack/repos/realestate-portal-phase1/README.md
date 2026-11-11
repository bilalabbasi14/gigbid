# Property Listings Portal – Phase 1

This repository contains the first phase of a real‑estate listings portal built for a regional agency in 2022. The application is a **Next.js** (v13) project written in **TypeScript** and styled with **Tailwind CSS**. It uses **Prisma** as the ORM to talk to a **PostgreSQL** database and is containerised with **Docker** for easy local development and production deployment.

## Architecture
- **Pages & API routes** – Server‑side rendered (SSR) pages live under `src/pages`. API routes (`/api/listings`) expose CRUD endpoints that interact with Prisma. The `getServerSideProps` function fetches listings for the home page, ensuring SEO‑friendly HTML.
- **Data layer** – Prisma client (`prisma/client.ts`) abstracts all DB calls. The schema defines `Listing`, `Agent`, and `Image` tables with relations and appropriate indexes for fast filtering.
- **Forms** – `react-hook-form` powers the listing submission form, providing validation and minimal re‑renders.
- **SEO** – `next-seo` config (`next-seo.config.ts`) supplies Open Graph and meta tags; the home page uses dynamic values based on the current listings.
- **Styling** – Tailwind utilities are configured in `tailwind.config.js`. The UI is fully responsive, with a mobile‑first grid for the listing cards.
- **Containerisation** – `Dockerfile` builds the app, and `docker-compose.yml` spins up both the Next.js container and a PostgreSQL instance. Environment variables (`DATABASE_URL`, `NEXT_PUBLIC_BASE_URL`) are injected at runtime.

## Getting Started
```bash
# clone the repo
git clone https://github.com/example/realestate-portal-phase1.git
cd realestate-portal-phase1

# install dependencies
npm ci

# set up the database (Docker) and run migrations
docker compose up -d db
npx prisma migrate deploy

# start the dev server
npm run dev
```
The site will be reachable at `http://localhost:3000`. The API can be tested at `http://localhost:3000/api/listings`.

## Production Build
```bash
npm run build && npm start
```
The Docker image can be built with `docker build -t realestate-portal .` and run with the provided `docker-compose.yml`.

---
*Lead Front‑end Engineer: Daniel Okafor*
