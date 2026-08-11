.PHONY: test lint typecheck run clean install help

PYTHON := python3
PYTEST := $(PYTHON) -m pytest
PYTHONPATH := $(shell pwd)/src:$$PYTHONPATH

help:
	@echo "StoryFlow Development Commands"
	@echo "=============================="
	@echo ""
	@echo "make test         - Run all unit and integration tests"
	@echo "make test-unit    - Run only unit tests"
	@echo "make test-int     - Run only integration tests"
	@echo "make lint         - Run code linting (ruff)"
	@echo "make typecheck    - Run type checking (mypy)"
	@echo "make clean        - Remove cache and compiled files"
	@echo "make install      - Install project dependencies"
	@echo "make dev          - Install development dependencies"
	@echo "make run          - Run FastAPI development server"
	@echo ""

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) tests/ -v

test-unit:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) tests/unit/ -v

test-int:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) tests/integration/ -v

lint:
	ruff check src/ tests/

typecheck:
	mypy src/ --ignore-missing-imports

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -name "*.pyc" -delete

run:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m uvicorn storyflow.main:app --reload
