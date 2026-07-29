.PHONY: install dev test lint format clean docs

install:
	pip install -e .

dev:
	pip install -e ".[all,dev]"

test:
	pytest tests/ -v

lint:
	ruff check aion_core/ aion_hand_cli/

format:
	black aion_core/ aion_hand_cli/
	ruff check --fix aion_core/ aion_hand_cli/

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage htmlcov/ .mypy_cache/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true

docs:
	@echo "Documentation generation not yet configured."
	@echo "Consider adding pdoc or mkdocs for auto-generated docs."
