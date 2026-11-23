# F1 evidence — parity, hardening, migration, UAT and go-live

Captured on 2026-11-21 against the current tree. Commands are reproducible from
the repository root; numbers are the output of those runs, not estimates.

## 1. Build and automated checks

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check src tests scripts` | All checks passed |
| Types | `mypy` | Success: no issues in 127 source files |
| Client | `npm run typecheck && npm run build` | Clean; `kwl.js` 55.2 kb |
| Menu parity | `kberp check menus` | Checks passed |
| View parity | `kberp check views` | Checks passed |
| Full suite | `make check` | **203 passed** in 73.5 s against a fresh `kberp_test_ci` |

## 2. Parity and security scorecard

`kberp check all`:

```
parity: menus 100.0% (202/202), actions 100.0% (130/130), 5 apps, settings groups: Technical
security: 111 models, 233 ACLs, 8 rules, 12 groups, 0 findings, 0 internal-write models
checks passed: menus, views, parity, security
```

The security audit fails only on high findings: a model without any ACL or an
unsafe production default. The internal-write model list is advisory because
service-layer writes use a superuser environment behind server-side guards.
Accounting is additionally gated at the app URL: a base internal user gets a
403 on deep links even though `accounting.move` keeps a read ACL for internal
users.

## 3. Performance (`prd.md` §2.3)

| Benchmark | Command | p50 | p95 | Budget |
|---|---|---:|---:|---:|
| 50-line confirm/post | `scripts/bench_posting.py` | 68.9 ms | **96.4 ms** | 1500 ms |
| Top 16 operational lists, 10,006 partners | `scripts/bench_lists.py` | see output | **87.5 ms worst** | 800 ms |
| Outbox emit → handler → processed | `scripts/bench_events.py` | 11.9 ms | **27.6 ms** | 5000 ms |

The list benchmark also asserts that query count does not grow with the page
size. The event benchmark drains pre-existing queue rows before timing so the
measurement is of the event under test.

## 4. Business UAT and accessibility

- `tests/test_uat.py` — UAT-01…09: launcher and parity, partner addresses/tags/
  banks, quote → delivery → invoice → payment, RFQ → approval → receipt → bill →
  payment, count/scrap/transfer with quants and ledger, partial payment
  reconciliation, delete/archive guard, restricted-user 403, and reports versus
  ledger and stock. **9 passed.**
- `tests/test_accessibility.py` — structural WCAG 2.2 AA smoke checks on login,
  launcher, app home, list, form and settings: language, single main landmark,
  skip link, unique ids, labelled controls, named buttons and an `h1`.
  **7 passed.**
- `tests/test_observability.py` — request IDs, structured request logs and the
  token-protected `/metrics` endpoint. **Passed.**
- `client/smoke.mjs` (`make smoke`) — real Chrome clicks through login, the
  build-stamp check, all five app shells and their first screens, contacts
  search and kanban, creating a contact, creating and confirming a quotation,
  creating its invoice and posting that invoice with object buttons.
  **21 checks passed, zero console or network errors** against the rebuilt
  containers.
- `client/menus.mjs` (`make smoke-menus`) — clicks every top-bar menu button and
  every menu link in all five apps: **132 controls, zero failures**. It checks
  the panel with `elementFromPoint()` as well as DOM state, which caught a CSS
  bug where `.menubar { overflow: hidden }` clipped every dropdown even though
  the menu logic was correct. Static assets now carry `?v=build_id` so browser
  caches are invalidated on each rebuild.
- `client/controls.mjs` (`make smoke-controls`) — clicks every New, view
  toggle, Search, filter and group-by control on each app's primary list:
  **50 controls, zero failures**.
- `tests/test_web.py::test_every_app_shell_renders` — production UI pass:
  no "Available screens", "No screens yet", "Delivery phase" or "Build status"
  copy; every app home renders a live KPI dashboard. The build stamp is hidden
  when `KB_DEBUG=0`.
- `make smoke-all` runs all three suites: **203 browser checks**. The runs also
  found and fixed a real search bug: text search on views containing a many2one
  field used `ILIKE` on an integer id and returned a 500; it now resolves the
  term against the related model's display name.
- `tests/test_security.py` and `tests/test_migration.py` — audit findings and
  all four importers, including dry-run safety, de-duplication, opening-balance
  balancing and draft stock counts. **All passed.**

These scripted UAT checks do not replace the stakeholder sign-off described in
[`cutover.md`](cutover.md) §6.

## 5. Migration

`kberp import` and `kberp import-templates` cover `partners`, `products`,
`opening_balances` and `stock_counts`. Imports are dry-run by default and need
`--commit` to write. Partners and products de-duplicate on external ID then
natural key; opening balances post one balanced entry per company; stock counts
create drafts unless `--validate` is passed. Templates are in
[`migration/templates/`](../migration/templates/).

No customer data was available in this environment, so only synthetic fixture
files and the reconciliation logic were exercised. A rehearsal on anonymised
production data remains a cutover gate.

## 6. Backup and restore drill

`make backup-drill` on the current tree:

```
source : kberp
dump   : kberp.dump (323,780 bytes, 0.5s)
target : kberp_restore_drill
tables : 118 compared, 0 mismatches
RPO    : MET (archive_mode=on, archive_timeout=60s, last WAL 000000010000000000000056 at 2026-11-21 08:09:21.361060+00:00, failures=0)
RTO    : MET (4.8s to restore, compare and smoke-test; budget 14400s)
drill passed
```

Compose now runs PostgreSQL with `wal_level=replica`, `archive_mode=on`,
`archive_timeout=60` and an archive command into the `kberp_wal-archive`
volume. The drill resets archiver counters, forces one WAL switch, waits for
the archive, restores the dump into a scratch database, compares every table's
row count and a 200-row sample hash, and boots the app against the copy with
the parity scorecard. Production must ship the WAL archive to durable storage
off the host; the local volume only proves the mechanism.

Procedures: [`runbook.md`](runbook.md), [`cutover.md`](cutover.md),
[`rollback.md`](rollback.md).

## 7. Deviations and follow-ups

| Area | Status |
|---|---|
| External penetration test | Not performed here; requires an independent tester before sign-off |
| Browser matrix and 360×640 check | Structural accessibility is automated; manual Chrome/Edge/Firefox/Safari checks remain a human task |
| Signed UAT | Scripts pass; the four role signatures in `cutover.md` are still blank |
| Customer migration rehearsal | Synthetic data only; real anonymised files must be dry-run on staging |
| PDF output | Reports render as print-ready HTML; `wkhtmltopdf` is not wired in |
| i18n / timezone | English only, UTC storage with no per-user locale/timezone preference UI (NFR-010/NFR-011 remain open) |
| Production hardening | Debug off, unique secrets, TLS proxy and durable WAL storage are documented requirements, not provisioned by this repository |
| Availability 99.5 % | Target documented; cannot be evidenced outside a monitored production month |
| Attachments | Mail is a local drop; attachments are not versioned (NFR-016 partially open) |

The exit criteria that can be verified from this repository are green. The
items above are explicit human or infrastructure follow-ups, not hidden gaps.
