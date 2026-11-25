.PHONY: help venv install client-install client-check up down logs reset init seed run worker test lint typecheck fmt check check-menus check-views bench backup-drill smoke smoke-menus smoke-controls smoke-all build-id deploy demo demo-reset

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
	@echo "make demo      build and start the full demo, then load demo documents"
	@echo "make demo-reset  wipe the demo database and rebuild it"
	@echo "make run       run the dev server against local PostgreSQL"
	@echo "make test      run the test suite"
	@echo "make check     lint + types + parity + tests"
	@echo "make bench     p95 list query on 10,000 partners"
	@echo "make backup-drill  dump, restore, compare and measure RPO/RTO"
	@echo "make smoke         drive the running UI with Chrome (21 checks)"
	@echo "make smoke-menus   click every top-bar menu in all five apps"
	@echo "make smoke-controls click every page-header control in all five apps"
	@echo "make smoke-all     run all three browser suites"
	@echo "make build-id      print the source hash baked into the container"
	@echo "make deploy        rebuild web/worker after a code change"
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

demo:
	docker compose up -d --build
	@$(MAKE) db-ready
	docker compose exec -T web kberp init --with-demo
	docker compose exec -T web kberp demo
	@until curl -fsS localhost:8069/readyz >/dev/null 2>&1; do sleep 1; done
	@echo "demo ready: http://localhost:8069 (admin / admin)"

demo-reset:
	docker compose down -v
	@$(MAKE) demo

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

backup-drill: db-ready
	$(PY) scripts/backup_drill.py

smoke:
	cd client && npm run smoke

smoke-menus:
	cd client && npm run smoke:menus

smoke-controls:
	cd client && npm run smoke:controls

smoke-all: smoke smoke-menus smoke-controls

build-id:
	@find src -type f ! -path '*/__pycache__/*' ! -name '*.pyc' -print0 \
	 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -c1-12

deploy:
	docker compose up -d --build web worker
	@until curl -fsS localhost:8069/readyz >/dev/null 2>&1; do sleep 1; done
	@echo "running build: $$(curl -fsS localhost:8069/readyz | $(PY) -c 'import json,sys; print(json.load(sys.stdin)["build_id"])')"

reset:
	docker compose down -v
	docker compose up -d db
	$(MAKE) db-ready
	$(MAKE) init
