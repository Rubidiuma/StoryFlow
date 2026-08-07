.PHONY: test lint typecheck run

test:
	UV_CACHE_DIR=.uv-cache uv run --extra dev pytest

lint:
	UV_CACHE_DIR=.uv-cache uv run --extra dev ruff check src tests

typecheck:
	UV_CACHE_DIR=.uv-cache uv run --extra dev mypy src tests

run:
	UV_CACHE_DIR=.uv-cache uv run uvicorn storyflow.main:app --host 127.0.0.1 --port 8000
