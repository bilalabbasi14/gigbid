FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 HF_HOME=/models OMP_NUM_THREADS=2
RUN pip install --no-cache-dir uv==0.13.1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY agent ./agent
COPY rag ./rag
COPY mcp_servers ./mcp_servers
COPY apps/__init__.py ./apps/__init__.py
COPY apps/api ./apps/api
COPY worker ./worker
COPY scripts ./scripts
COPY gigsim ./gigsim
COPY evals/__init__.py evals/thresholds.yaml ./evals/
COPY evals/runners ./evals/runners
COPY data/__init__.py ./data/__init__.py
COPY data/policy_pack ./data/policy_pack
COPY data/personas ./data/personas
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
# pre-download the open embedding and reranker models into the image (no network at runtime)
RUN python -c "from rag import embeddings; embeddings.warm()" || echo "model prefetch skipped"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
