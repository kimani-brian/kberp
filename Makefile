.PHONY: help venv install client-install client-check up down logs reset init seed run worker test lint typecheck fmt check check-menus check-views bench

PY := .venv/bin/python
PIP := .venv/bin/pip

help:
	@echo "make install   install package + dev deps into .venv"
	@echo "make client-install   install KWL client npm dependencies"
	@echo "make client-check     typecheck and rebuild static/js/kwl.js"
	@echo "make up        start PostgreSQL and web via Docker Compose"
	@echo "make down      stop the stack"
	@echo "make db-up     start only PostgreSQL"
	@echo "make init      create schemas/tables and load XML metadata"
	@echo "make seed      load demo data"
	@echo "make run       run the dev server against local PostgreSQL"
	@echo "make test      run the test suite"
	@echo "make check     lint + types + parity + tests"
	@echo "make bench     p95 list query on 10,000 partners"
	@echo "make check-menus / check-views   metadata parity checks"
	@echo "make reset     drop and recreate the database (destructive)"

venv:
	python3.12 -m venv .venv

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -e '.[dev]'

client-install:
	cd client && npm ci

client-check:
	cd client && npm run typecheck && npm run build

up:
	docker compose up --build -d

down:
	docker compose down

db-up:
	docker compose up -d db

logs:
	docker compose logs -f web

db-ready:
	@until docker compose exec -T db pg_isready -U kberp -d kberp >/dev/null 2>&1; do sleep 1; done

init: db-ready
	$(PY) -m kberp.cli init --with-demo

seed: db-ready
	$(PY) -m kberp.cli seed

run: db-ready
	$(PY) -m kberp.cli run --reload

worker: db-ready
	$(PY) -m kberp.cli worker

test: db-ready
	$(PY) -m pytest

lint:
	$(PY) -m ruff check src tests scripts

typecheck:
	$(PY) -m mypy

check-menus: db-ready
	$(PY) -m kberp.cli check menus

check-views: db-ready
	$(PY) -m kberp.cli check views

fmt:
	$(PY) -m ruff format src tests scripts

check: lint typecheck client-check check-menus check-views test

bench: db-ready
	$(PY) scripts/bench_list.py

reset:
	docker compose down -v
	docker compose up -d db
	$(MAKE) db-ready
	$(MAKE) init
