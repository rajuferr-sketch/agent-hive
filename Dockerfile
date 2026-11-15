# AgentHive — production container image
# Advanced multi-agent orchestration system (1 Master Agent + 20 specialized AI agents)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---- Dependencies + package -------------------------------------------------
# Copy metadata first for better layer caching (README.md is referenced by
# pyproject.toml's `readme` field, so it must be present at build time).
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# ---- Application assets ------------------------------------------------------
COPY configs/ ./configs/
COPY scripts/ ./scripts/
COPY .env.example ./.env.example

# ---- Runtime user ------------------------------------------------------------
RUN useradd --create-home --uid 1000 hive \
    && mkdir -p /app/workspace /app/data \
    && chown -R hive:hive /app

USER hive

EXPOSE 8000

# Liveness probe: the FastAPI app must serve /health on API_PORT (default 8000).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://127.0.0.1:8000/health', timeout=4).raise_for_status()"

CMD ["agent-hive", "start"]
