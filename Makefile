.PHONY: test lint typecheck run clean install dev help

help:
	@echo "StoryFlow Development Commands"
	@echo "=============================="
	@echo ""
	@echo "make test         - Run all unit and integration tests"
	@echo "make lint         - Run code linting (ruff)"
	@echo "make typecheck    - Run type checking (mypy)"
	@echo "make run          - Run FastAPI development server"
	@echo "make install      - Install project (with pip)"
	@echo "make dev          - Install project with dev dependencies"
	@echo "make clean        - Remove cache and compiled files"
	@echo ""

# Primary workflow using uv (if available)
test:
	UV_CACHE_DIR=.uv-cache uv run --extra dev pytest || PYTHONPATH=src python3 -m pytest tests/ -v

lint:
	UV_CACHE_DIR=.uv-cache uv run --extra dev ruff check src tests || ruff check src tests

typecheck:
	UV_CACHE_DIR=.uv-cache uv run --extra dev mypy src tests || mypy src tests --ignore-missing-imports

run:
	UV_CACHE_DIR=.uv-cache uv run uvicorn storyflow.main:app --host 127.0.0.1 --port 8000 || PYTHONPATH=src python3 -m uvicorn storyflow.main:app --reload

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name .uv-cache -exec rm -rf {} +
	find . -name "*.pyc" -delete
