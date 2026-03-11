FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# LightGBM dependency
RUN apt-get update && apt-get install -y libgomp1

WORKDIR /app

# Copy dependency files first (cache layer)
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev deps in prod)
RUN uv sync --frozen --no-dev

# Copy app code
COPY app.py ./
COPY models/preprocessor.joblib ./models/
COPY scripts/data_clean_utils.py ./scripts/
COPY run_information.json ./

EXPOSE 8000

CMD ["uv", "run", "python", "app.py"]