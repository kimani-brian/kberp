# KB ERP

[![CI](https://github.com/kimani-brian/kberp/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/kimani-brian/kberp/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL 16](https://img.shields.io/badge/postgresql-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Node 22](https://img.shields.io/badge/node-22-5FA04E?logo=nodedotjs&logoColor=white)](https://nodejs.org/)

An Odoo-shaped ERP for five interconnected applications: **Contacts, Sales,
Purchase, Inventory, Accounting**.

This repository is being built phase by phase, exactly as planned in
[`phases.md`](phases.md). Current status: **P0 through A3 and F1 complete from
the repository side**; the external penetration test and stakeholder sign-offs
remain before production go-live. The platform shell, KWL client, realtime bus,
shared contact directory and the interconnected document chains are running.
Sales tracks delivered and invoiced quantities through payment. Purchase runs
from vendor pricing and RFQs through receipts, bills, three-way match,
agreements, approvals and landed costs. Accounting has a chart of accounts, a
tax engine, immutable postings, payments, credit notes, currency differences,
lock dates, assets, bank matching, eTIMS payloads and balanced statements.
Inventory adds replenishment, perpetual valuation, barcode scanning and the full
configuration set to counts, scrap, lots and traceability. Each app opens on a
live dashboard rather than a development "Available screens" list.

The interface is sky blue on cloud white rather than Odoo's maroon: a deep sky
for actions and links, a soft wash at the top of each page, and white work
surfaces so tables and forms stay calm.

## Documents

| Document | Purpose |
|---|---|
| [`prd.md`](prd.md) | Scope, menu parity baseline, requirements, UAT |
| [`architecture.md`](architecture.md) | Stack, modules, ORM, services, deployment |
| [`rules.md`](rules.md) | Boundaries, coding rules, business invariants |
| [`design.md`](design.md) | Launcher, shell, views, per-module screens |
| [`phases.md`](phases.md) | Phase plan, gates, estimates |
| [`docs/adr/`](docs/adr/) | Decisions: ORM/schemas, view engine, client strategy |
| [`BUILD.md`](BUILD.md) | Live build log with every phase's evidence and deliberate deviations |
| [`docs/f1-evidence.md`](docs/f1-evidence.md) | F1 parity, security, performance, UAT and restore-drill results |
| [`docs/runbook.md`](docs/runbook.md) | Daily operations, health checks and common incidents |
| [`docs/cutover.md`](docs/cutover.md) | Go-live gates, change window, reconciliation and hypercare |
| [`docs/rollback.md`](docs/rollback.md) | Rollback triggers, restore procedure and post-mortem |

## Quick start

```bash
cp .env.example .env
make install        # Python 3.12 venv with dev dependencies
make client-install # npm dependencies for the KWL client
make db-up          # PostgreSQL 16 on localhost:5433
make init           # schemas, tables, XML menus/actions/views, demo data
make run            # http://localhost:8069  (admin / admin)
make worker         # outbox + scheduled jobs
make check          # lint, types, client build, parity, tests
make bench          # p95 list query on 10,000 partners
make backup-drill   # dump, restore, compare 118 tables, measure RPO/RTO
make smoke          # drive the running UI with Chrome (21 checks)
make smoke-all      # smoke + every top-bar menu + every page control
```

After changing Python, templates or the client bundle, rebuild the containers —
they copy the source at image build time:

```bash
make deploy         # rebuild web/worker and print the running build id
make build-id       # hash of the current source; must match the top-right stamp
```

If the stamp in the top bar differs from `make build-id`, the browser is talking
to a stale container. Rebuild with `make deploy` and hard-refresh the page.

Operations and go-live procedures are in `docs/runbook.md`,
`docs/cutover.md` and `docs/rollback.md`.

Start Redis and set `KB_REDIS_URL=redis://localhost:6379/0` if you want the
WebSocket to wake on pub/sub. Without Redis the bus still delivers every
message through its database poll.

See [`BUILD.md`](BUILD.md) for every phase's exit checklists and deviations,
and [`docs/f1-evidence.md`](docs/f1-evidence.md) for the final scorecard.

Or the whole stack in containers:

```bash
docker compose up --build -d
docker compose exec web kberp init --with-demo
curl -s localhost:8069/readyz   # database, registry and redis
```

## Layout

```
src/kberp/
├── config.py        settings from environment
├── db.py            connection pool and helpers
├── env.py           request environment (db, user, context)
├── registry.py      module discovery, dependencies, model registry
├── installer.py     schema and table creation, XML metadata loading
├── parity.py        menu fixture and view/action/menu checks
├── orm/             fields, models, domains
├── xml/             Odoo-style XML loader (menus, actions, views)
├── services/        outbox, worker, scheduled jobs and the durable bus
├── web/             Werkzeug app, auth, routes, renderers, WebSocket endpoint
├── addons/          base (kernel) + contacts, sales, purchase, inventory, accounting
client/              TypeScript KWL client (signals, router, RPC, list/form views)
```

Cross-module rules from `rules.md` are enforced from the start: a module may import
only its declared dependencies, and business data is reached through services — never
through another module's tables.

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, coding rules and the test
gate, and [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) for how we work together.
Keep pull requests focused, include a regression test, and run `make check`
before opening one.

Report suspected vulnerabilities privately through the repository's Security
tab as described in [`SECURITY.md`](SECURITY.md). Do not open a public issue for
them.
