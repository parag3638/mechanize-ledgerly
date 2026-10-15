# Ledgerly Incident — see PROJECT.md §11 for which phase implements each target.
# Tools run through uv so they use the locked versions.

.DEFAULT_GOAL := help
# Long jobs keep a Mac awake (sleep pauses the Docker VM mid-run). No-op elsewhere.
AWAKE := $(shell command -v caffeinate >/dev/null 2>&1 && echo caffeinate -is)
.PHONY: help check scan dev-up dev-down dev-shell dev-logs dev-test loadtest baseline build task grade qa qa-fast runs view bundle refs-build refs-encrypt refs-decrypt

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

# BACKEND.md §10. pytest exits 5 when no tests are collected; treat that as a pass until the first test lands.
check: ## Lint, type-check and test the host-side code, then scan
	uv run ruff format --check . && uv run ruff check . && uv run pyright && { uv run pytest -q; rc=$$?; [ $$rc -eq 0 ] || [ $$rc -eq 5 ]; }
	$(MAKE) scan

# .venv is skipped: its packages are covered by the uv.lock vulnerability scan; their bundled files are not ours to fix.
scan: ## Semgrep + Trivy over the repo
	semgrep scan --config auto --error && trivy fs --scanners vuln,secret,misconfig --skip-dirs .venv --exit-code 1 .

DEV = docker compose -p ledgerly-dev -f task/compose.yaml -f task/compose.dev.yaml

dev-up: ## Build and start the Ledgerly stack locally (host ledgerly/ bind-mounted, hot reload)
	$(DEV) up -d --build --wait --wait-timeout 240

dev-down: ## Stop the local stack and delete its volumes (fresh database next time)
	$(DEV) down -v --remove-orphans

dev-shell: ## Shell in the dev container as the agent's user
	$(DEV) exec -u dev dev bash

dev-logs: ## Follow logs: make dev-logs SVC=worker
	$(DEV) logs -f --tail 100 $(SVC)

dev-test: ## Run the Ledgerly test suite inside the dev container
	$(DEV) exec -T -u dev dev make test

loadtest: ## Replay the public load profile inside the dev container
	$(DEV) exec -T -u dev dev make loadtest

baseline: ## Capture INC-2041 from the unfixed stack: snapshot, incident artifacts, facts (~15 min)
	$(AWAKE) uv run python task/baseline/make_baseline.py

INSPECT = uv run inspect
GRADE = $(AWAKE) $(INSPECT) eval task/ledgerly_incident.py --model mockllm/model --max-sandboxes 1 --log-dir runs/logs/grade
SUBMISSION ?= probes/unmodified
REPLAY_RUNS ?= 3

build: ## Build all task images
	docker compose -p ledgerly-build -f task/compose.yaml build

task: build ## Build, then grade the unmodified repo through Inspect (expect a score <= 0.1)
	$(GRADE) -T submissions=probes/unmodified -T replay_runs=$(REPLAY_RUNS)
	uv run python -m taskqa.show runs/logs/grade

grade: ## Grade a submission dir (patch.diff + actions.sh): make grade SUBMISSION=.refs/A
	$(GRADE) -T submissions=$(SUBMISSION) -T replay_runs=$(REPLAY_RUNS)
	uv run python -m taskqa.show runs/logs/grade

qa: ## Run all 7 taskqa checks -> QA_REPORT.md + qa/report.html (hours; resumable)
	$(AWAKE) uv run python -m taskqa run --replay-runs 3

qa-fast: ## taskqa with one replay run per profile (quick iteration; not for the report)
	$(AWAKE) uv run python -m taskqa run --replay-runs 1 --n 3 --k 3 --out qa-fast

AGENT ?= codex_cli
# Cost guard: one run and a hard token cap per run unless asked for more.
N ?= 1
TOKEN_LIMIT ?= 1000000
AGENT_MODEL ?= openai/$(OPENAI_AGENT_MODEL)

runs: ## Frontier agent runs (capped): make runs AGENT=codex_cli N=1 TOKEN_LIMIT=1000000 AGENT_MODEL=openai/<id>
	$(AWAKE) $(INSPECT) eval task/ledgerly_incident.py --model $(AGENT_MODEL) -T solver=$(AGENT) \
		--epochs $(N) --token-limit $(TOKEN_LIMIT) --max-sandboxes 1 --log-dir runs/logs/agents

view: ## Open the Inspect log viewer on runs/logs
	$(INSPECT) view --log-dir runs/logs

bundle: ## Build the static log viewer into www/ for GitHub Pages
	$(INSPECT) view bundle --log-dir runs/logs/agents --output-dir www --overwrite

refs-build: ## Assemble reference submissions and reference-derived probes in .refs/
	uv run python -m taskqa.refs build

refs-encrypt: ## Encrypt .refs/ into references.tar.age (LEDGERLY_REFS_PASSPHRASE)
	uv run python -m taskqa.refs encrypt

refs-decrypt: ## Decrypt references.tar.age into .refs/
	uv run python -m taskqa.refs decrypt
