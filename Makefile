.PHONY: setup lint format typecheck test check doctor

setup:
	uv sync
	uv run pre-commit install

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest -m "not llm"

check: lint typecheck test

doctor:
	uv run rpg-agent doctor

test-llm:
	uv run pytest -m llm -s
