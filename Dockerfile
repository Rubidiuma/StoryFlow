FROM python:3.12-slim

WORKDIR /app

# Install dependencies via uv
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv \
    && uv sync --no-dev --frozen --no-install-project

# Copy application source
COPY src/ /app/src/

# Ensure data directory exists (will be overridden by mounted volume)
RUN mkdir -p /data

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV STORYFLOW_ENVIRONMENT="production"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health')" || exit 1

# Use $PORT from Render (falls back to 8000 locally)
CMD ["sh", "-c", "exec uvicorn storyflow.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
