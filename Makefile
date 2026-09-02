.PHONY: install test lint format build docker-build docker-check docker-run

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

docker-build:
	docker compose build

docker-check:
	docker compose run --rm --entrypoint odoo-project-mcp-admin odoo-project-mcp check

docker-run:
	docker compose run --rm -T odoo-project-mcp
