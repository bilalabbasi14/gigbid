# One image for the three GigBid MCP servers; the command selects which one(s) to run.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy HF_HUB_DISABLE_SYMLINKS_WARNING=1
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY agent ./agent
COPY rag ./rag
COPY mcp_servers ./mcp_servers
COPY data/policy_pack ./data/policy_pack
COPY data/personas ./data/personas
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8101 8102 8103
CMD ["python", "-m", "mcp_servers.run_all"]
