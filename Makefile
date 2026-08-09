.PHONY: install dev test lint format typecheck clean docs help

install:
	pip install -e .

dev:
	pip install -e ".[all,dev]"

test:
	pytest tests/ -v --tb=short

test-cov:
	pytest tests/ --cov=aion_core --cov-report=term-missing --cov-report=html

lint:
	ruff check aion_core/ aion_hand_cli/ tests/ --select=F
	ruff check aion_core/ aion_hand_cli/ tests/ --select=E,W,UP --statistics

format:
	black aion_core/ aion_hand_cli/ tests/
	ruff check --fix aion_core/ aion_hand_cli/ tests/

typecheck:
	mypy aion_core/ --ignore-missing-imports || true

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage htmlcov/ .mypy_cache/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true

docs:
	@echo "Documentation generation not yet configured."
	@echo "Consider adding pdoc or mkdocs for auto-generated docs."

help:
	@echo "Available targets:"
	@echo "  install    - Install package editable"
	@echo "  dev        - Install with all extras + dev deps"
	@echo "  test       - Run tests"
	@echo "  test-cov   - Run tests with coverage"
	@echo "  lint       - Run ruff linter"
	@echo "  format     - Run black + ruff fix"
	@echo "  typecheck  - Run mypy"
	@echo "  clean      - Remove build artifacts"