.PHONY: help setup run test lint docker-up docker-down restart

IMAGE_NAME := e-bank-api
CONTAINER_NAME := e-bank-api
PORT := 3000
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
	@echo "Targets:"
	@echo "  setup        Create venv and install dev dependencies"
	@echo "  run          Start API locally with hot reload (port $(PORT))"
	@echo "  test         Run test suite"
	@echo "  lint         Run ruff (auto-fix + format) on app/ and tests/"
	@echo "  docker-up    Build image and start container in background"
	@echo "  docker-down  Stop and remove container"
	@echo "  restart      Restart Docker container (down + up)"

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

docker-build:
	docker build -t $(IMAGE_NAME) .

docker-up: docker-build
	-docker rm -f $(CONTAINER_NAME) 2>/dev/null
	docker run -d --name $(CONTAINER_NAME) -p $(PORT):3000 $(IMAGE_NAME)

docker-down:
	-docker rm -f $(CONTAINER_NAME)

restart: docker-down docker-up

$(VENV)/bin/%:
	@test -d $(VENV) || (echo "Run 'make setup' first." && exit 1)
