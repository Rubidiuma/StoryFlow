FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --no-dev --frozen

FROM python:3.12-slim
LABEL maintainer="StoryFlow"
LABEL description="AI-driven interactive fiction — StoryFlow"

RUN groupadd -r storyflow && useradd -r -g storyflow storyflow

WORKDIR /app
COPY --from=builder /build/.venv /app/.venv
COPY src/ /app/src/

RUN mkdir -p /data && chown storyflow:storyflow /data

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV STORYFLOW_ENVIRONMENT="production"
ENV STORYFLOW_HOST="0.0.0.0"
ENV STORYFLOW_PORT="8000"

VOLUME /data

USER storyflow

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "storyflow.main:app", "--host", "0.0.0.0", "--port", "8000"]
