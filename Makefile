.PHONY: test lint typecheck run

test:
	UV_CACHE_DIR=.uv-cache uv run --extra dev pytest

lint:
	UV_CACHE_DIR=.uv-cache uv run --extra dev ruff check src/storyflow/main.py src/storyflow/config.py tests/unit/test_health.py

typecheck:
	UV_CACHE_DIR=.uv-cache uv run --extra dev mypy src/storyflow/main.py src/storyflow/config.py

run:
	UV_CACHE_DIR=.uv-cache uv run uvicorn storyflow.main:app --host 127.0.0.1 --port 8000
