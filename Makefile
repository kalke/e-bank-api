.PHONY: help setup setup-oidc run test lint lint-ci ci migrate migrate-down migration db-shell \
	ensure-env docker-config docker-build up docker-up docker-down docker-restart \
	docker-logs docker-debug docker-prod restart auth-up auth-down auth-token \
	ebank-m2m-token smoke-oidc up-all down-all

COMPOSE := docker compose
COMPOSE_PROD := $(COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml
KALKE_AUTH_DIR ?= ../kalke-auth
OIDC_ISSUER_DEFAULT ?= http://localhost:8443/realms/kalke
OIDC_AUDIENCE_DEFAULT ?= e-bank-api

PORT := 3000
DOCKER_PORT := 8000
HOST := 0.0.0.0

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn
PYTEST := $(VENV)/bin/pytest
RUFF := $(VENV)/bin/ruff

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Local development:"
	@echo "  setup          Create venv and install dev dependencies"
	@echo "  setup-oidc     Write local OIDC_* into .env for kalke-auth"
	@echo "  run            Start API locally with hot reload (port $(PORT))"
	@echo "  test           Run test suite"
	@echo "  lint           Run ruff (auto-fix + format) on app/ and tests/"
	@echo "  lint-ci        Run ruff checks only (no modifications, for CI)"
	@echo "  ci             Run lint-ci and test"
	@echo "  migrate        Apply Alembic migrations"
	@echo ""
	@echo "Docker + kalke-auth:"
	@echo "  auth-up        Start sibling kalke-auth IdP"
	@echo "  up-all         auth-up + API stack"
	@echo "  up             Start API stack (needs network kalke-auth)"
	@echo "  smoke-oidc     Token → POST /event without body (expect 422)"
	@echo "  auth-token     Demo user JWT from kalke-auth"
	@echo "  ebank-m2m-token M2M JWT for e-bank-api"

setup:
	python -m venv $(VENV)
	$(PIP) install -r requirements-dev.txt
	@if [ -d "$(KALKE_AUTH_DIR)" ]; then \
		if [ ! -f "$(KALKE_AUTH_DIR)/.env" ] && [ -f "$(KALKE_AUTH_DIR)/.env.example" ]; then \
			cp "$(KALKE_AUTH_DIR)/.env.example" "$(KALKE_AUTH_DIR)/.env"; \
			echo "Created $(KALKE_AUTH_DIR)/.env"; \
		fi; \
	fi

setup-oidc: ensure-env ## Write local OIDC_* into .env
	@grep -vE '^(OIDC_ENABLED|OIDC_ISSUER|OIDC_AUDIENCE|OIDC_DISCOVERY_URL)=' .env > .env.tmp || true
	@printf 'OIDC_ENABLED=true\nOIDC_ISSUER=%s\nOIDC_AUDIENCE=%s\nOIDC_DISCOVERY_URL=http://caddy:8443/realms/kalke\n' \
		"$(OIDC_ISSUER_DEFAULT)" "$(OIDC_AUDIENCE_DEFAULT)" >> .env.tmp
	@mv .env.tmp .env
	@echo "Wrote OIDC_* for kalke-auth (audience=$(OIDC_AUDIENCE_DEFAULT))"

run: $(UVICORN)
	$(UVICORN) app.main:app --host $(HOST) --port $(PORT) --reload

test: $(PYTEST)
	OIDC_ENABLED=false $(PYTEST) -v

lint: $(RUFF)
	$(RUFF) check --fix app tests
	$(RUFF) format app tests

lint-ci: $(RUFF)
	$(RUFF) check app tests
	$(RUFF) format --check app tests

ci: lint-ci test

migrate:
	alembic upgrade head

migrate-down:
	alembic downgrade -1

migration:
	alembic revision --autogenerate -m "$(name)"

db-shell:
	docker compose exec postgres psql -U ebank -d ebank

ensure-env:
	@test -f .env || cp .env.example .env

docker-config: ensure-env
	$(COMPOSE) config

docker-build: ensure-env
	$(COMPOSE) build

auth-up:
	@$(MAKE) -C "$(KALKE_AUTH_DIR)" up

auth-down:
	@$(MAKE) -C "$(KALKE_AUTH_DIR)" down

auth-token:
	@$(MAKE) -C "$(KALKE_AUTH_DIR)" -s token

ebank-m2m-token:
	@$(MAKE) -C "$(KALKE_AUTH_DIR)" -s ebank-m2m-token

up-all: auth-up up

down-all: docker-down auth-down

up: ensure-env
	@docker network inspect kalke-auth >/dev/null 2>&1 || { \
		echo "Missing Docker network kalke-auth. Start IdP first: make auth-up"; \
		exit 1; \
	}
	$(COMPOSE) up --build

docker-up: ensure-env
	@docker network inspect kalke-auth >/dev/null 2>&1 || { \
		echo "Missing Docker network kalke-auth. Start IdP first: make auth-up"; \
		exit 1; \
	}
	$(COMPOSE) up --build -d

docker-down:
	$(COMPOSE) down

docker-restart: docker-down docker-up

restart: docker-restart

docker-logs:
	$(COMPOSE) logs -f

docker-debug: ensure-env
	$(COMPOSE) --profile debug up --build

docker-prod: ensure-env
	$(COMPOSE_PROD) up --build -d

smoke-oidc: ## Token → POST /event (expect 422 = auth OK)
	@TOKEN=$$($(MAKE) -s auth-token); \
	code=$$(curl -sS -o /tmp/ebank-smoke.json -w '%{http_code}' \
	  -X POST "http://localhost:$(DOCKER_PORT)/event" \
	  -H "Authorization: Bearer $$TOKEN" \
	  -H "Content-Type: application/json" \
	  -d '{}'); \
	echo "HTTP $$code"; cat /tmp/ebank-smoke.json; echo; \
	test "$$code" = "422"

$(VENV)/bin/%:
	@test -d $(VENV) || (echo "Run 'make setup' first." && exit 1)
