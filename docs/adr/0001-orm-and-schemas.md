# ADR 0001 — Registry-driven ORM on PostgreSQL schemas

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-15 |
| Context | P0 platform |

## Decision

Models are Python classes registered by module manifests. A metaclass collects
`Field` instances into `_fields`; the installer turns those into PostgreSQL
columns. Every model owns one table inside its module schema and every read or
write goes through `BaseModel` (`search`, `read`, `create`, `write`, `unlink`),
never through raw SQL in a module.

Domains are Odoo-shaped lists compiled to parameterised SQL. Many2one values are
stored as integers and expanded to `{id, name}` on read, with expansion batched
to one query per relation so list pages cannot become N+1.

## Why

- The XML views, actions and security rules need runtime field metadata; a
  declarative registry gives that for free.
- Odoo compatibility is a product requirement, so field names and domain syntax
  should feel familiar to anyone porting a module.
- Schema-per-module keeps module ownership visible in the database and makes
  later extraction or auditing tractable.
- Parameterised SQL plus a compiler that rejects unknown fields protects the
  boundary without a second query builder dependency.

## Consequences

- Adding a field means changing Python; the installer then adds the column
  idempotently. There is not yet a migration DSL, so destructive changes need a
  deliberate migration step.
- Each ORM call currently commits independently. Multi-step business flows will
  need an explicit transaction/unit-of-work context in P0.2.
- Rich types (computed, related, x2many) arrive incrementally; the registry was
  designed to accept them without changing call sites.
