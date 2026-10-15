.PHONY: test loadtest migrate lint format

test: ## Run the test suite (uses the ledgerly_test database)
	python -m pytest

loadtest: ## Replay the public load profile against the running stack
	python tools/loadtest.py

migrate: ## Apply pending Alembic migrations as the migrator role
	alembic upgrade head

lint:
	ruff check . && ruff format --check .

format:
	ruff format . && ruff check --fix .
