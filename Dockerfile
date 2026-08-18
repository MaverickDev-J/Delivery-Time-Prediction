FROM python:3.12-slim

# Install uv binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install libgomp1 for LightGBM OpenMP support and curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create non-root runtime user
RUN useradd -m -u 1000 appuser

# Copy dependency specifications first for layer caching
COPY pyproject.toml uv.lock ./

# Install production dependencies
RUN uv sync --frozen --no-dev

# Copy application and contract packages
COPY --chown=appuser:appuser contracts/ ./contracts/
COPY --chown=appuser:appuser core/ ./core/
COPY --chown=appuser:appuser scripts/ ./scripts/
COPY --chown=appuser:appuser models/ ./models/
COPY --chown=appuser:appuser app.py ./
COPY --chown=appuser:appuser run_information.json* ./

ENV PATH="/app/.venv/bin:$PATH"

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "app.py"]