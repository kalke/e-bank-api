.PHONY: help setup run test lint lint-ci ci \
	ensure-env docker-config docker-build docker-up docker-down docker-restart \
	docker-logs docker-debug docker-prod restart

COMPOSE := docker compose
COMPOSE_PROD := $(COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml

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
	@echo "  run            Start API locally with hot reload (port $(PORT))"
	@echo "  test           Run test suite"
	@echo "  lint           Run ruff (auto-fix + format) on app/ and tests/"
	@echo "  lint-ci        Run ruff checks only (no modifications, for CI)"
	@echo "  ci             Run lint-ci and test"
	@echo ""
	@echo "Docker Compose (API + Redis on port $(DOCKER_PORT)):"
	@echo "  docker-up      Start stack in background"
	@echo "  docker-down    Stop and remove stack"
	@echo "  docker-restart Restart stack"
	@echo "  docker-build   Build compose images"
	@echo "  docker-config  Validate compose configuration"
	@echo "  docker-logs    Follow compose logs"
	@echo "  docker-debug   Start stack with Redis Commander (port 8081)"
	@echo "  docker-prod    Start production stack (4 workers)"
	@echo "  restart        Alias for docker-restart"

setup:
	python -m venv $(VENV)
	$(PIP) install -r requirements-dev.txt

run: $(UVICORN)
	$(UVICORN) app.main:app --host $(HOST) --port $(PORT) --reload

test: $(PYTEST)
	$(PYTEST) -v

lint: $(RUFF)
	$(RUFF) check --fix app tests
	$(RUFF) format app tests

lint-ci: $(RUFF)
	$(RUFF) check app tests
	$(RUFF) format --check app tests

ci: lint-ci test

ensure-env:
	@test -f .env || cp .env.example .env

docker-config: ensure-env
	$(COMPOSE) config

docker-build: ensure-env
	$(COMPOSE) build

docker-up: ensure-env
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

$(VENV)/bin/%:
	@test -d $(VENV) || (echo "Run 'make setup' first." && exit 1)
