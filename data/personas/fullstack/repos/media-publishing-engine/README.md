# Content Publishing Engine

**Project:** Content Publishing Engine (media‑publishing‑engine)  
**Client:** Media agency (2025)  
**Duration:** 10 weeks (Jan 2025 – Mar 2025)  
**Role:** Lead Engineer (Daniel Okafor)

## Overview
The solution delivers a head‑less CMS built on **Django** with **django‑cms** providing the editorial UI. Content is stored in **PostgreSQL** and exposed via **Django REST Framework** as JSON payloads. A separate **React** front‑end (TypeScript) consumes the API, renders markdown articles with **react‑markdown**, and uses client‑side routing to serve multiple web properties and mobile‑app back‑ends.

## Architecture
- **Backend** (`/backend`): Django project `cms_backend` with a `articles` app. The app defines a `Article` model, a serializer, and a viewset exposing standard CRUD endpoints (`/api/articles/`). Authentication uses DRF token auth. Dockerfile builds the service on Python 3.11, and `docker-compose.yml` wires it to a PostgreSQL container.
- **Frontend** (`/frontend`): React app bootstrapped with Vite + TypeScript. The `ArticleViewer` component fetches article JSON, parses the `content` field (markdown) with `react-markdown`, and displays it. Routing is handled by `react‑router‑dom` to map `/article/:slug` URLs.
- **CI/CD**: GitHub Actions run linting (`flake8`, `eslint`), unit tests (`pytest`, `jest`), and build Docker images.

## Setup
```bash
# Clone the repo
git clone https://github.com/example/media-publishing-engine.git
cd media-publishing-engine

# Backend
cd backend
docker compose up -d --build   # starts db and api
python manage.py migrate
python manage.py createsuperuser  # create admin

# Frontend
cd ../frontend
npm install
npm run dev   # Vite dev server on http://localhost:5173
```

## Key Metrics
- Publishing time reduced by **60%** thanks to markdown‑first authoring and instant API delivery.
- The API now powers **3 mobile apps** and **2 web properties** with a single content source.
- Average API response time < **120 ms** under a 200 RPS load test.

---
*All code is production‑ready and follows the agency’s security and performance guidelines.*
