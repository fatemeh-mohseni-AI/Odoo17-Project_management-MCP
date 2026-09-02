.PHONY: install test lint format build

install:
	uv sync --extra dev

test:
	uv run pytest --cov=odoo_project_mcp --cov-report=term-missing

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src

format:
	uv run ruff check --fix .
	uv run ruff format .

build:
	docker build -t odoo17-project-mcp:local .

