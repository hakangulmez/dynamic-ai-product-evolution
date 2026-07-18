.PHONY: setup test lint contamination schema workflow notebook ui

setup:
	./scripts/setup_local.sh

test:
	pytest -q

lint:
	ruff check .

contamination:
	pytest -q tests/contamination

schema:
	python -m dynamic_ai_products.validation schemas

workflow:
	python -m dynamic_ai_products.workflow

notebook:
	jupyter lab notebooks/00_MASTER_PIPELINE.ipynb

ui:
	./scripts/run_research_console.sh
