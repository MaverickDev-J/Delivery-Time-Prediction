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
COPY contracts/ ./contracts/
COPY core/ ./core/
COPY scripts/ ./scripts/
COPY models/ ./models/
COPY app.py ./
COPY run_information.json* ./

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uv", "run", "python", "app.py"]