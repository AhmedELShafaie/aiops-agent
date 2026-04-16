SHELL := /bin/bash

.PHONY: test test-unit test-local

test:
	@if command -v docker >/dev/null 2>&1; then \
		$(MAKE) test-unit; \
	else \
		echo "Docker not found; falling back to local Python test run."; \
		$(MAKE) test-local; \
	fi

test-unit:
	docker compose run --rm unit-tests

test-local:
	@if ! command -v python3 >/dev/null 2>&1; then \
		echo "python3 not found. Install Python 3.11+ or use Docker."; \
		exit 1; \
	fi
	@python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" || \
		( echo "Python 3.11+ is required for local tests. Current: $$(python3 --version 2>&1)"; exit 1 )
	@python3 -m pytest -q tests/unit
