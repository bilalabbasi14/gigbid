# Route Optimization Service (logistics‑route‑optimizer)

**Overview**

This repository contains the core of a vehicle‑routing‑problem (VRP) solver built for a large logistics enterprise in 2025. The service ingests a list of delivery stops (latitude, longitude, demand) and a fleet description, computes near‑optimal routes using a custom heuristic built on **NetworkX**, and serves the results through a **FastAPI** endpoint. The application is containerised with **Docker** and packaged for deployment on **AWS SageMaker** as a scalable inference endpoint.

**Architecture**

- **api/** – FastAPI application (`main.py`) exposing `/solve` (POST) and `/health` endpoints.
- **solver/** – Core routing logic (`vrp_solver.py`). Uses NetworkX to construct a complete graph, applies a Clarke‑Wright savings heuristic, and refines routes with 2‑opt swaps.
- **Dockerfile** – Multi‑stage build: Python base image → install dependencies → copy source → expose port 8080.
- **requirements.txt** – Pinpointed versions for reproducibility.
- **deployment/** – Example SageMaker inference container configuration (Docker image URI, IAM role placeholder).

**Setup**

```bash
# Clone and enter the repo
git clone https://github.com/example/logistics-route-optimizer.git
cd logistics-route-optimizer

# Build the Docker image
docker build -t route-optimizer:latest .

# Run locally
docker run -p 8080:8080 route-optimizer:latest
```

The service will be reachable at `http://localhost:8080`. Send a JSON payload to `/solve` as described in the API docs (see `api/main.py`).

**Key design decisions**

- **NetworkX** provides a flexible graph abstraction; we avoid heavyweight OR‑tools to keep the container lightweight.
- The Clarke‑Wright heuristic runs in O(N²) time, suitable for up to ~500 stops per request within the 2‑second SLA.
- 2‑opt post‑processing improves route quality at a modest CPU cost.
- FastAPI’s async support allows concurrent request handling, essential for batch inference on SageMaker.
- Docker multi‑stage build reduces final image size to ~150 MB, meeting SageMaker’s container limits.

**Performance**

During internal testing (Jan 2025) on an m5.large instance, average route distance dropped 14 % versus the legacy manual planner, and on‑time delivery rose to 96 %. The service handled 120 concurrent requests with <1.8 s latency per solve.

---

*Priya Raman – Algorithm Engineer (2025)*
