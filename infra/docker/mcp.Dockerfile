# The three GigBid MCP servers (portfolio, marketplace, workspace) over streamable HTTP with bearer
# auth on 8101-8103. The portfolio server alone is also published for others (see its README).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 HF_HOME=/models OMP_NUM_THREADS=2
RUN pip install --no-cache-dir uv==0.13.1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
# models depend only on the config: code changes never re-download the weights
COPY agent/config.yaml ./agent/config.yaml
RUN .venv/bin/python -c "import yaml; from sentence_transformers import SentenceTransformer, CrossEncoder; m = yaml.safe_load(open('agent/config.yaml'))['models']; SentenceTransformer(m['embeddings']['model'], device='cpu')"
COPY agent ./agent
COPY rag ./rag
COPY mcp_servers ./mcp_servers
COPY apps/__init__.py ./apps/__init__.py
COPY apps/api ./apps/api
COPY gigsim ./gigsim
COPY data/__init__.py ./data/__init__.py
COPY data/policy_pack ./data/policy_pack
COPY data/personas ./data/personas
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8101 8102 8103
CMD ["python", "-m", "mcp_servers.run_all"]
