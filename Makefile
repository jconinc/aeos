.PHONY: format lint types test compatibility integration verify wheel

format:
	ruff format src tests

lint:
	ruff check src tests

types:
	PYTHONPATH=src mypy src/aeos_kernel

test:
	PYTHONPATH=src python3.12 -m pytest -m "not compatibility and not integration" --cov=aeos_kernel --cov-report=term-missing -q

compatibility:
	PYTHONPATH=src:$${AEOS_MULTIAGENT_SOURCE_ROOT:-/home/john/code/MultiAgentCommunication} python3.12 -m pytest -q -m compatibility

integration:
	@test -n "$$AEOS_MEMGRAPH_TEST_PORT" || (echo "AEOS_MEMGRAPH_TEST_PORT is required" >&2; exit 2)
	PYTHONPATH=src python3.12 -m pytest -q -m integration

verify: lint types test compatibility

wheel:
	python3.12 -m pip wheel . --no-deps --wheel-dir dist
