# KB ERP

An Odoo-shaped ERP for five interconnected applications: **Contacts, Sales,
Purchase, Inventory, Accounting**.

This repository is being built phase by phase, exactly as planned in
[`phases.md`](phases.md). Current status: **P0, C1, S1, A1, I1, S2, A2, P1, P2,
I2, I3, P3 and A3 complete**. The platform shell, KWL client, realtime bus,
shared contact directory and the interconnected document chains are running.
Sales tracks delivered and invoiced quantities through payment. Purchase runs
from vendor pricing and RFQs through receipts, bills, three-way match,
agreements, approvals and landed costs. Accounting has a chart of accounts, a
tax engine, immutable postings, payments, credit notes, currency differences,
lock dates, assets, bank matching, eTIMS payloads and balanced statements.
Inventory adds replenishment, perpetual valuation, barcode scanning and the full
configuration set to counts, scrap, lots and traceability.

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
| [`BUILD.md`](BUILD.md) | Live build log, P0/C1/S1/A1/I1/S2/A2/P1/P2/I2/I3/P3/A3 evidence, deliberate deviations |

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
```

Start Redis and set `KB_REDIS_URL=redis://localhost:6379/0` if you want the
WebSocket to wake on pub/sub. Without Redis the bus still delivers every
message through its database poll.

See [`BUILD.md`](BUILD.md) for the P0, C1, S1, A1, I1, S2, A2, P1, P2, I2,
I3, P3 and A3 exit checklists, evidence and the deliberate deviations.

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
