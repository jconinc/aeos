.PHONY: format lint types test compatibility verify wheel

format:
	ruff format src tests

lint:
	ruff check src tests

types:
	PYTHONPATH=src mypy src/aeos_kernel

test:
	PYTHONPATH=src python3.12 -m pytest --cov=aeos_kernel --cov-report=term-missing -q

compatibility:
	PYTHONPATH=src:/home/john/code/MultiAgentCommunication python3.12 -m pytest -q -m compatibility

verify: lint types test compatibility

wheel:
	python3.12 -m pip wheel . --no-deps --wheel-dir dist

