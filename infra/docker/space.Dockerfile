# All-in-one image for a single-container free host (Hugging Face Docker Space, Render, Railway).
# One public port ($PORT, default 7860) serves the Next.js app, which proxies /api to FastAPI on
# 127.0.0.1:8000. Inside: GigSim (unless GIGSIM_BASE_URL points elsewhere), the API with the MCP
# servers mounted in-process, the Arq worker and a local Redis. Postgres (pgvector) is external:
# set DATABASE_URL (e.g. a free Neon database).

FROM node:22-slim AS web
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1 API_URL=http://127.0.0.1:8000
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 HF_HOME=/app/models OMP_NUM_THREADS=2 \
    APP_ENV=production GIGBID_IN_PROCESS_MCP=1 PORT=7860 NEXT_TELEMETRY_DISABLED=1
RUN apt-get update && apt-get install -y --no-install-recommends redis-server tini && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.13.1
COPY --from=web /usr/local/bin/node /usr/local/bin/node
RUN useradd -m -u 1000 app && mkdir -p /app && chown app /app
USER app
WORKDIR /app
COPY --chown=app pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH"
# models depend only on the config, so code changes never re-download ~1.5 GB of weights
COPY --chown=app agent/config.yaml ./agent/config.yaml
RUN python -c "import yaml; from sentence_transformers import SentenceTransformer, CrossEncoder; m = yaml.safe_load(open('agent/config.yaml'))['models']; SentenceTransformer(m['embeddings']['model'], device='cpu'); CrossEncoder(m['reranker']['model'], device='cpu')"
COPY --chown=app agent ./agent
COPY --chown=app rag ./rag
COPY --chown=app mcp_servers ./mcp_servers
COPY --chown=app apps/__init__.py ./apps/__init__.py
COPY --chown=app apps/api ./apps/api
COPY --chown=app worker ./worker
COPY --chown=app scripts ./scripts
COPY --chown=app gigsim ./gigsim
COPY --chown=app evals/__init__.py evals/thresholds.yaml ./evals/
COPY --chown=app evals/runners ./evals/runners
COPY --chown=app data/__init__.py ./data/__init__.py
COPY --chown=app data/policy_pack ./data/policy_pack
COPY --chown=app data/personas ./data/personas
RUN uv sync --frozen --no-dev && mkdir -p /app/data/processed
COPY --from=web --chown=app /web/.next/standalone ./web
COPY --from=web --chown=app /web/.next/static ./web/.next/static
COPY --from=web --chown=app /web/public ./web/public
EXPOSE 7860
ENTRYPOINT ["tini", "--"]
CMD ["bash", "scripts/serve_all.sh"]
