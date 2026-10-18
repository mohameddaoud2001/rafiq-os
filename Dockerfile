FROM python:3.12-slim AS base
WORKDIR /app
RUN pip install uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY data ./data
RUN uv sync --frozen || uv sync
EXPOSE 7860 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD uv run python -c 'import os, httpx; httpx.get("http://localhost:" + os.environ.get("PORT", "7860") + "/health", timeout=2)'
CMD ["sh", "-c", "uv run uvicorn rafiq.api.main:app --host 0.0.0.0 --port ${PORT:-7860}"]

FROM base AS mcp-turath
EXPOSE 8001
CMD ["uv", "run", "python", "-m", "rafiq.mcp_servers.turath", "--http"]

FROM base AS mcp-ibadat
EXPOSE 8002
CMD ["uv", "run", "python", "-m", "rafiq.mcp_servers.ibadat", "--http"]

FROM base AS mcp-live
EXPOSE 8003
CMD ["uv", "run", "python", "-m", "rafiq.mcp_servers.live", "--http"]
