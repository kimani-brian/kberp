# KB ERP — Build Log

| Field | Value |
|---|---|
| Current phase | **A3 — Closing, reporting, compliance and full parity** |
| Current increment | **A3 complete — statements, lock dates, assets, bank matching and eTIMS** |
| Status | P0, C1, S1, A1, I1, S2, A2, P1, P2, I2, I3, P3 and A3 complete; all five apps reach their planned menu parity |
| Last updated | 2026-11-19 |
| Document of record | [`phases.md`](phases.md) §5 |

This file is the living build log. It records what exists, the evidence that it
works, and every deliberate deviation from the plan so later phases do not
inherit surprises.

---

## 1. What runs today

```bash
cp .env.example .env
make install                       # .venv with runtime + dev dependencies
make client-install                # npm dependencies for the KWL client
make db-up                         # PostgreSQL 16 on localhost:5433
make init                          # schemas, tables, XML metadata, demo data
make run                           # http://localhost:8069  (admin / admin)
make worker                        # outbox + ir.cron loop
make client-check                  # typecheck and rebuild static/js/kwl.js
```

Redis is optional in development. Set `KB_REDIS_URL=redis://localhost:6379/0`
when you want the WebSocket to wake on pub/sub instead of its 750 ms database
poll. The bus keeps working either way because PostgreSQL owns the messages.

Container path (verified):

```bash
docker compose up -d --build
curl -s http://localhost:8069/health          # ok
curl -s http://localhost:8069/readyz          # database, registry, redis all ok
```

CLI surface:

| Command | Purpose |
|---|---|
| `kberp init [--with-demo] [--fresh]` | Idempotent install/upgrade of every module |
| `kberp seed` | Demo partners and products |
| `kberp run [--host --port --reload]` | Development Werkzeug server |
| `kberp worker [--once --interval]` | Outbox drain and scheduled jobs |
| `kberp emit <event> [--payload JSON]` | Enqueue a transactional outbox event |
| `kberp check [menus\|views\|all]` | Parity and referential metadata checks |

---

## 2. Delivered in P0.1 and P0.2

### Platform

- **Package and layout** — `src/kberp` modular monolith, addons at
  `src/kberp/addons/{base,contacts,sales,purchase,inventory,accounting}`.
- **Decisions and CI** — ADRs for the ORM/schema model, view engine and client
  strategy; GitHub Actions workflow for lint, types, parity and tests.
- **Registry** — manifest discovery, dependency resolution, topological module
  order, model collection, handler import. Six modules install in order:
  `base, contacts, sales, accounting, purchase, inventory`.
- **Installer** — creates eight schemas, synchronises tables and columns
  idempotently, seeds groups, currencies, countries, UoMs, the demo company,
  administrator and heartbeat cron, loads XML metadata, records module state.
- **Database** — psycopg 3 connection pool, explicit transactions, schema and
  column helpers. PostgreSQL 16 in Compose.

### ORM and metadata

- Field types: `Char, Text, Integer, Boolean, Float, Monetary, Date, Datetime,
  Selection, Many2one, StringList`; audit columns added by the metaclass.
- Domain compiler with prefix `&`, `|`, `!`, implicit AND, `=`, `!=`, comparisons,
  `in`, `not in`, `like`, `ilike`, NULL handling and safe `order_by`.
- Recordsets and records with lazy load, change tracking, `create/write/unlink`,
  required-field validation, unknown-field rejection, unique indexes.
- ACLs from `core.ir_model_access` with `perm_read/perm_write/perm_create/perm_unlink`.
  Administrator bypass, per-request cache, deny-by-default.
- 21 models: module, menu, window action, client action, view, ACL, group, user,
  session, partner, country, state, company, currency, UoM category/UoM, product
  category/template, outbox event, cron and chatter message.
- XML loader for `record`, `menuitem` and `delete`: views, actions, menus,
  security rows, idempotent by `xml_id`.

### Web shell

- Werkzeug 3 application with routing, DB-backed sessions, Argon2id passwords,
  CSRF (login cookie + session token), flash messages proven per session.
- Launcher with five app cards in sequence order, descriptions and per-app accent.
- App switcher overlay (`Alt+W`), functional menus from the database, breadcrumbs,
  app home, deep links, keyboard focus states and reduced-motion support.
- Generic list, search/filter, pager, form, create/edit/delete and JSON-RPC.
- Views are parsed from `core.ir_ui_view.arch`; no field list is hard-coded in the
  template. A test renames a column in the database and asserts the list follows.
- Chat: a minimal chatter stream on every form, with author and timestamp.
- 403, 404 and validation error pages; static asset traversal blocked.
- Bootstrap 5.3.3 vendored locally; `kberp.css` implements the `design.md`
  tokens and the five app accents.

### Platform services

- Transactional outbox `emit()` plus a worker that claims pending rows
  (`FOR UPDATE SKIP LOCKED`), retries with attempt counts and dead-letters at
  `max_attempts` with the error captured.
- Handler registry imported from manifests; `platform.ping` and a scheduled
  `heartbeat` ship as demonstrable jobs.
- `ir.cron` runner reschedules successful jobs by their interval and failed jobs
  one minute later.
- Settings → Technical screens for Products, Units of Measure, Product Categories
  and Outbox Events.

### P0.2 — KWL client and realtime bus

The server-rendered screens stay the contract and the fallback. KWL adds a
TypeScript client that renders the same payloads without a full page load.

- **Client build** — `client/` is a strict TypeScript project bundled by esbuild
  to `src/kberp/web/static/js/kwl.js`. `make client-check` runs `tsc --noEmit`
  and rebuilds the bundle.
- **Small runtime** — signals for route and connection state, a category
  registry, a JSON-RPC client with CSRF, a history router, a single aria-live
  toast region, and list/form renderers.
- **Progressive enhancement** — links to `/apps/<app>/action/<id>` are
  intercepted. A newer navigation increments a render token, so a slow response
  cannot overwrite the screen the user asked for last. Server-rendered HTML is
  still what arrives on first load and what runs without JavaScript.
- **Forms** — list and form payloads come from `view.load`, `view.form`,
  `view.save` and `view.unlink`. New records receive model defaults, so `active`
  starts ticked and `type` starts at Contact. Boolean, selection, many2one,
  number, date and text widgets share the same field spec.
- **Permissions** — payloads carry `can_create`, `can_write` and `can_unlink`
  from the ACL service. Read-only screens explain the limit instead of showing
  a button that will fail.
- **Durable bus** — `platform.bus_message` is the source of truth. The worker
  broadcasts each processed outbox event to the `platform` channel. Redis
  pub/sub only wakes the WebSocket; a 60-minute cron prunes old rows.
- **Two transports** — `/web/bus` accepts a WebSocket and falls back to a
  four-second poll when WebSocket is missing or the handshake stalls. The
  client tracks `last` id across reconnects, and both transports read the same
  rows. A poll response is applied before `last` advances, so a batch is never
  skipped.
- **Close path** — the WebSocket handler hangs up the raw socket before the
  WSGI envelope finishes. Werkzeug therefore cannot write HTTP headers after
  the frames, and the browser does not report an invalid frame.
- **Health** — `/healthz` is process liveness, `/readyz` checks the database,
  registry and Redis. Compose waits for `db` and `redis` health before starting
  `web` and `worker`.

### C1 — Contact directory core

Partner data lives in `base` (`core.*`) because every app consumes it. Contacts
owns the screens, configuration and demonstrations.

- **Directory model** — people and companies with `parent_id`, address `type`,
  function, email, phone, mobile, website, VAT, company registry, industry, tags,
  language and a full address block. `complete_name` and `commercial_partner_id`
  are stored columns maintained by the model, so search and grouping use them
  without recomputing a lineage per query.
- **Address rules** — company address fields flow down to `type=contact`
  children; VAT flows up to the commercial entity; registry and industry delegate
  to it. `address_get()` returns the closest address of each requested type, from
  the commercial partner or a matching child, and rejects cycles when a parent is
  set.
- **Banks** — account numbers are stripped to alphanumerics and upper-cased,
  unique per partner through validation and a composite index; BIC is upper-cased.
  Tags are hierarchical with colours and their own child-of domains.
- **Safety** — archive instead of delete; archiving a partner tied to an active
  user is refused; deleting a referenced partner fails with a readable message.
- **Security** — internal users read contacts; create, write and delete are for
  the partner-manager group. `core.ir_rule` record rules AND global rules and OR
  group rules, with `"$company"` resolved from the current company, and the
  default search scope hides archived rows unless the domain or context asks.
- **Screens** — list (name, email, phone, salesperson, city, country, tags and a
  statistics column), kanban with avatar, parent badge, tags and footer
  statistics, form with Person/Company radio and the Contacts / Sales & Purchase /
  Invoicing / Notes tabs, search filters (Companies, Persons, Archived) and
  group-by chips.
- **Grouped views** — `read_group` counts one relational, selection or boolean
  field at a time; the server and KWL render the same group headers, counts and
  capped card sets. Group-by survives search, filters, view switches and paging.
- **Statistics** — `Partner.statistics()` counts addresses and bank accounts for a
  page in two queries; the list shows badges instead of a blank cell.
- **Chatter** — messages, followers, activities and done toggles, all reachable
  from the form and from web endpoints. Notes posted from the browser are written
  after the action and model are verified.
- **Configuration** — hierarchical contact tags, industries, banks and bank
  accounts beneath Contacts → Configuration; the whole C1 menu scope is in the
  parity fixture.
- **Theme** — the shell now uses deep sky blue on cloud white (`design.md` §2.1),
  with a soft sky wash at the top of the page, tinted launcher tiles, segmented
  Person/Company switch and quieter stat and group chips.

### S1 — Quotation core and confirmation

Sales now owns its first document chain. It depends on `base`, `accounting` and
`inventory`, so those modules install before it.

- **Schema** — `sales.order`, `sales.order_line` and `sales.settings` in the
  `sales` schema, `accounting.tax` for rates and `inventory.picking` with
  `inventory.move` for the delivery request. Core gained a minimal
  `core.pricelist` and `core.ir_sequence`.
- **Document infrastructure** — `Database.transaction()` binds one connection
  to a request or job, so a confirmation and its delivery commit as one unit.
  A model can expose `One2many` lines and named object buttons, and views can
  declare a report. These are the seams later document phases reuse.
- **Pricing** — `recompute_totals()` keeps line subtotals and order amounts in
  stored columns. Discounts apply per line, taxes group by rate and amounts are
  quantised to the order currency. The browser sends raw values, the server
  decides the money.
- **Transitions** — `send`, `confirm`, `cancel` and `reset` live in
  `sales.services.orders`. Each checks the current state, writes a chatter note
  and rejects a repeat with a clear message. Confirm creates one draft delivery
  per warehouse group, stamps the order date and emits
  `sales.order.confirmed` in the same transaction. Cancel cancels non-done
  pickings.
- **Numbering** — `SO/YYYY/NNNNN` and `OUT/NNNNN` come from atomic sequence
  updates. Repeating a confirmation for the same origin returns the existing
  delivery, so a retry never creates a second one.
- **Screens** — quotations and orders lists with search filters and grouping,
  a kanban, a form with status bar, object buttons, editable line table and a
  totals panel. The server template and KWL build the same DOM. Smart buttons
  show address and bank counts on contacts and deliveries on an order.
- **Report and mail** — `Preview` opens a printable QWeb-style quotation with
  addresses, lines, taxes and terms. Sending writes the rendered document to a
  local mail drop as an attachment and queues `sales.quotation.sent`.
- **Security** — sales user and manager groups, read-only internal users, a
  company record rule on orders, and ACLs on taxes and deliveries.

### A1 — Ledger core, taxes and posting

Accounting now owns the double-entry ledger that other apps post into.

- **Schema** — `accounting.account`, `journal`, `fiscal_year`, `settings`,
  `move`, `move_line`, `audit_log`, `tax_group` and `tax_repartition`. A small
  chart of accounts, five journals with sequences, default accounts and a VAT
  group are installed with the module.
- **Tax engine** — `compute_taxes()` handles percentage and fixed rates,
  included and excluded prices, per line or per total rounding, multiple taxes
  and repartitions with their own accounts. Sales keeps calling the same API.
- **Posting** — `post()` checks that debit equals credit, allocates the journal
  number from an atomic sequence, writes state and audit rows, and emits
  `accounting.move.posted` inside the caller's transaction. Unbalanced entries
  report both totals.
- **Immutability** — a posted move and its lines reject writes and deletes for
  every caller, including the administrator. Cancellation keeps the number and
  reversal creates and posts a compensating entry. Both write audit rows.
- **Invoices and bills** — `recompute_move()` builds product, tax and
  receivable or payable lines, so invoice totals equal untaxed plus taxes and
  posting leaves the matching account balances.
- **Screens** — journal entries, invoices, bills, chart of accounts, taxes, tax
  groups, journals, fiscal years, currencies and settings. The accounting app
  home shows revenue, expenses, profit, cash and draft or posted counts.
- **Security** — accounting user, manager and auditor groups, read-only
  internal users, a company record rule, and the posted-entry guard in the
  model layer.

### I1 — Warehouse core, transfers and quants

Inventory now owns the stock ledger and the transfer services the commercial
apps call.

- **Schema** — `inventory.warehouse`, `location`, `operation_type`, `quant`,
  `picking`, `move` and `move_line`. A demo warehouse, its three virtual
  locations, the WH/Stock location and three operation types with sequences are
  installed with the module.
- **Services** — `create_receipt`, `create_delivery`, `create_internal`,
  `reserve`, `validate`, `cancel` and `available_qty` live in
  `inventory.services.api`. Sales still calls `create_delivery` and
  `cancel_deliveries`, so confirmation and cancellation use one code path.
- **Quants** — on-hand and reserved quantities are stored per product and
  location. Reservation locks the selected quant rows and takes stock oldest
  first. Validation writes both sides of each move in the caller's transaction.
- **Guards** — negative stock is rejected with the available and requested
  amounts unless settings allow it. Done transfers and their lines are
  immutable. A partial validation creates a backorder for the remainder.
- **Reports and screens** — receipts, deliveries, internal transfers and all
  transfers with lists, kanban, forms and status bars, plus warehouses,
  operation types, locations, stock, settings and an overview with to receive,
  to deliver, late and stock value cards.
- **Security** — inventory user and manager groups, company rules on transfers
  and quants, and read-only access for internal users.

### S2 — Order to invoice and fulfillment feedback

Sales now closes the loop from delivery back to the order and into an invoice.

- **Schema** — orders and lines carry `qty_delivered`, `qty_invoiced`,
  `invoice_status`, `invoice_policy`, `locked` and tags. Small `sales.tag` and
  `sales.header_footer` models back the configuration screens.
- **Fulfillment service** — `recompute()` rebuilds delivered quantities from
  done pickings and invoiced quantities from invoice lines, then derives the
  order status. It runs from the inventory and accounting event handlers, so a
  repeated event cannot double count.
- **Invoicing** — `create_invoice()` creates one draft invoice for the
  remaining quantity, using the order's origin, taxes, currency and terms.
  Ordered-quantity policy invoices the full order after confirmation; delivered
  policy invoices only what has been shipped.
- **Guards** — a locked order rejects field writes in the model layer, with
  chatter notes still available. Over-invoicing raises a readable error and an
  invoice beyond the ordered quantity marks the order as upselling.
- **Screens** — To Invoice and Orders to Upsell queues, Create Invoice, Lock and
  Unlock buttons, delivered and invoiced columns on order lines, plus tag and
  header and footer configuration.

### A2 — Invoicing, payments, reconciliation and multi-currency

Accounting now closes the receivables and payables loop.

- **Schema** — `accounting.payment`, `payment_line`, `payment_term` and
  `fiscal_position`. Invoices carry `amount_residual`, `payment_state`, payment
  terms and a frozen currency rate. An exchange difference account is seeded.
- **Payments** — `register_payment()` allocates one payment over one or more
  invoices of the same partner, posts the bank move in the caller's transaction
  and refreshes each invoice. Partial payments set Partial; full ones set Paid.
  Overpayment is rejected with the outstanding amount in the message.
- **Credit notes** — `create_credit_note()` prefills the invoice lines as
  negatives. Posting the credit note reduces the invoice residual and sets
  Reversed through the accounting event handler.
- **Currency** — the invoice stores the rate used at creation. A payment at a
  different rate posts a balanced exchange-difference line in company currency.
- **Screens** — customer and vendor payments, credit notes and refunds, payment
  terms and fiscal positions. Invoice forms show Register Payment and Credit
  Note buttons with residual and payment state.

### P1 — RFQ core and receipt request

Purchase now mirrors Sales on the buying side and hands confirmations to
Inventory.

- **Schema** — `purchase.order`, `purchase.order_line`, `purchase.settings` and
  `purchase.vendor_price`. A demo supplier with quantity-break prices is
  installed, and orders number as `PO/YYYY/NNNNN`.
- **Vendor pricing** — `vendor_price()` selects by vendor, product, quantity,
  currency and validity dates, taking the largest qualifying minimum quantity.
  New lines default to that price and the supplier's lead time.
- **State machine** — `send`, `confirm` and `cancel` run as object actions with
  state guards. Confirm requests one receipt through
  `inventory.services.api.create_receipt` in the same transaction; cancel
  cancels non-done receipts.
- **Screens** — RFQ and purchase order lists, kanban, forms and search, vendor
  pricelists, settings, a printable order and a receipts smart button. Receipt
  and billing status fields are present as stubs for P2.

### P2 — Receive to bill and 3-way match

Purchase now tracks what arrived and what was billed against what was ordered.

- **Schema** — order lines carry `qty_received` and `qty_billed`; orders carry
  `locked`, `bill_control` and a vendor warning alongside the derived receipt
  and invoice status fields.
- **Feedback** — `billing.recompute()` rebuilds received quantities from done
  pickings, including backorders, and billed quantities from vendor bills.
  Inventory and accounting events call it, so a repeated event cannot double
  count.
- **Billing** — `create_bill()` respects the policy. Ordered policy bills the
  full ordered quantity once anything is received; received policy bills only
  what has arrived. Over-billing and a second bill with nothing left are
  rejected with readable messages.
- **Guards** — a locked purchase order rejects field writes in the model layer,
  and Unlock restores editing. Cancel still cancels draft receipts.
- **Screens** — the order form shows ordered, received and billed columns in
  the line editor, status chips, and Create Bill, Lock and Unlock buttons. P2
  adds no new menus.

### I2 — Adjustments, lots, packages and traceability

Inventory now records why stock changed and can follow a lot through the chain.

- **Schema** — `inventory.lot` with a product and company uniqueness key,
  `package_type`, `package`, `stock_count`, `count_line` and `scrap`. Move lines
  carry a lot and a package, and settings toggle lot, expiry and package
  tracking.
- **Counts** — a count sheet prefills expected quantity from available stock.
  Validation creates and validates adjustment pickings for each difference, so
  quant changes still come from moves rather than direct edits.
- **Scrap** — validation moves stock to the inventory loss location and emits a
  valuation payload with the reason, user and quantity for I3 to post.
- **Traceability** — `traceability()` returns the receipt, internal moves and
  delivery chain for a lot. Moves History, Moves Analysis and Traceability
  screens are backed by the move list and search views.
- **Audit** — empty outbox handlers publish count and scrap events on the bus,
  so processed events do not dead-letter.

### I3 — Procurement, valuation, barcode and full configuration

Inventory now reorders stock, values it into the ledger and supports scanning.

- **Schema** — `inventory.route`, `rule`, `orderpoint`, `storage_category`,
  `putaway_rule`, `barcode_nomenclature`, `delivery_method`, `zip_prefix` and
  `valuation_layer`. Settings gained valuation accounts, a journal and lot,
  expiry and package switches.
- **Replenishment** — the scheduler checks every active orderpoint against
  on-hand plus incoming stock and creates one RFQ for the shortfall through
  `purchase.services.api.create_rfq`. An orderpoint remembers its last RFQ, so
  a second run never duplicates it.
- **Valuation** — perpetual mode posts one balanced entry per stock move,
  keyed by a unique valuation layer on `move_id`. Receipts value into stock,
  deliveries and scrap post their offsets, and internal transfers create no
  entry. The Stock Valuation report reads the layers.
- **Barcode** — a scan field on transfer forms calls `inventory.scan` through
  JSON-RPC, parses product, lot and quantity from the active nomenclature, and
  adds or increases a move line with immediate feedback.
- **Configuration** — routes, pull rules, storage categories, putaway rules,
  barcode nomenclatures, delivery methods, zip prefixes and product variant
  links, plus the Performance report.

### P3 — Agreements, approvals, reporting and landed costs

Purchase now controls what it commits to and what the stock is worth.

- **Schema** — `purchase.agreement` and `agreement_line` for blanket orders,
  `landed_cost` and `landed_cost_line`, approval fields on orders and a
  `purchase.settings.approval_threshold`. Vendor price history feeds on-time
  and purchase-line suggestions.
- **Agreements and call-offs** — an agreement carries validity dates and
  ordered, called-off and remaining quantities. A call-off creates an RFQ
  linked to the agreement and is refused when the quantity or date falls
  outside the agreement.
- **Approvals** — orders above the configured threshold (seeded at 250,000)
  enter `waiting` and create no receipt. A purchase manager's `action_approve`
  confirms the order and writes the approval to the chatter. Directly writing
  `state = "purchase"` is rejected unless the caller sets the explicit
  `allow_confirmed` context, so the API cannot bypass the queue.
- **Vendor performance and analysis** — on-time rate and history-backed line
  suggestions sit beside a Purchase analysis that groups confirmed order lines
  by vendor, product and category and reconciles with their totals.
- **Landed costs** — a landed cost allocates each cost line across the done
  moves of a receipt by equal split, quantity or value. The allocation bumps
  the matching valuation layers (creating an `adjust` layer when valuation is
  periodic) and posts a balanced entry debiting stock and crediting the landed
  cost account. Customs imports reuse the same model from Accounting.
- **Reminders** — an `ir.cron` job emails receipt reminders using the
  days-before setting, and vendor warnings surface on the RFQ.

### A3 — Closing, reporting, compliance and full parity

Accounting can now close a period, prove the figures and meet the Kenyan
e-invoicing requirement.

- **Schema** — lock dates, tax returns and lines, asset models, assets and
  depreciation lines, loans and loan lines, deferrals and recognition lines,
  reconciliation models, bank statements and lines, report definitions and
  lines, analytic plans and accounts, budgets and lines, follow-up levels,
  payment providers, methods, tokens and transactions, EDI documents and a
  shared `config_item`. Moves gained `secured`; journal items gained `tax_id`
  and `analytic_account_id`.
- **Closing controls** — one `accounting.lock_date` row holds sales, purchase
  and hard locks. Posting or writing a move on or before the lock is rejected
  with the date and reason. Securing an entry writes an audit row and makes
  the move and its lines immutable; reversal remains the correction path.
- **Statements and reports** — `reporting.run` regenerates 19 report types:
  balance sheet, profit and loss, cash flow, trial balance, general and
  partner ledgers, aged receivable and payable, tax, EC sales, fiscal, invoice
  analysis, analytic, executive summary, unrealized currencies,
  billed-not-received, bill-to-receive, invoices-to-be-issued and
  invoiced-not-delivered. The balance sheet carries current profit into
  equity, so assets equal liabilities plus equity after every run.
- **Assets, loans and deferrals** — straight-line schedules compute from the
  asset model and post balanced depreciation, principal/interest and revenue
  recognition entries. Posting marks each schedule line with its entry.
- **Reconciliation and tax** — bank statements import CSV-style rows, match
  them to payments and journal entries, and write off small residuals with a
  balanced entry. Tax returns compute from posted tax lines; eTIMS payloads
  are generated only for posted customer invoices and are idempotent.
- **Remaining configuration** — account groups, tags, fiscal categories,
  multi-ledger, cash roundings, checks, return types, horizontal groups,
  online synchronization, incoterms, tax units, OSCU codes/notices and
  analytic models share filtered views over `config_item`, each with its own
  action and menu. Follow-up levels drive the customer reminder cron.
- **Parity** — the Accounting tree now matches the A3 menu list, including
  Transactions, Assets & Liabilities, Closing, Review, Reporting,
  Configuration, KRA eTIMS, Online Payments, Analytic Accounting and
  Vendors → Customs Imports.

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Lint | `make lint` | clean |
| Types | `make typecheck` | clean (mypy, 124 files) |
| Client types | `make client-check` | `tsc --noEmit` clean; bundle **55.2 KB** |
| Unit + integration | `make test` | **169 passed** |
| Menu parity | `make check-menus` | root diff = 0 against `tests/parity/menus.json` (phase A3, 202 menus) |
| View/action/menu refs | `make check-views` | clean; virtual `statistics` and one2many subview fields are accounted for |
| List performance | `make bench` | p95 **23.1 ms** on 10,000 partners; **10 constant queries** per list load |
| Compose smoke | `docker compose up -d --build` | db, redis, web, worker healthy; `/readyz` all ok; worker broadcast observed |
| Browser smoke | Chrome via Playwright | C1 through I3 flows, then P3 approvals/landed costs and A3 lock dates, asset depreciation, a balanced balance sheet, eTIMS, budgets and analytic items; no console errors |

The list path was measured after fixing a real N+1: many2one labels were fetched
once per row; `BaseModel.read()` now batches expansion to one query per relation.

---

## 3. P0 exit criteria (phases.md §5)

| Criterion | State | Evidence |
|---|---|---|
| Compose up → login → `/apps` shows five cards in sequence | Met | `test_launcher_lists_five_apps_in_sequence`; Compose smoke |
| Reachable by keyboard, working app switcher and deep links | Met | `kberp.js` Alt+W / Escape / focus handling; Chrome smoke covered launcher, deep link, list and form |
| Every app shell renders its menu tree from the database | Met | `test_every_app_shell_renders`, `test_view_path_comes_from_the_database` |
| Root parity diff = 0 | Met | `tests/parity/menus.json`, `make check-menus` |
| Partner and product create/edit through generic views | Met | `test_create_and_edit_partner_writes_audit_and_chatter`, `test_create_product_through_settings` |
| Audit rows written | Met | same tests; `create_uid/write_uid/create_date/write_date` asserted |
| Chatter message written | Met (minimal stream) | `chatter.message` row asserted after create/edit |
| Outbox event emitted, consumed, retried, dead-lettered | Met | `tests/test_events.py` |
| Install/upgrade idempotent on a blank database | Met | `test_init_is_idempotent`; repeated `kberp init` |
| Lint, types, unit, integration, view/menu checks green | Met | table in §2 |
| p95 list query < 800 ms on 10,000 partners, no N+1 | Met | `make bench`: 10.8 ms, 7 queries |

P0.2 closes the two items that were deferred from the original skeleton: the
KWL/TypeScript renderers and the WebSocket bus with Redis fan-out. Both now run
in development and Compose. The P0 gate is satisfied; C1 can start.

---

## 3a. C1 exit criteria (phases.md §5)

| Criterion | State | Evidence |
|---|---|---|
| UAT-02: company, two addresses, tag and bank account; correct `complete_name`; address sync both ways | Met | `test_partner_kind_complete_name_and_commercial`, `test_address_sync_company_to_contact_children_only`, `test_address_get_prefers_the_right_level`, `test_bank_account_is_normalised_and_unique_per_partner` |
| VAT sync, commercial partner, parent cycle and bank uniqueness tests pass; deleting a referenced partner is blocked with a readable message | Met | `test_vat_syncs_up_to_the_company`, `test_parent_cycle_is_rejected`, `test_delete_is_blocked_when_referenced` |
| A user without the partner-manager group sees contacts read-only and gets 403 on direct writes | Met | `test_restricted_user_is_read_only`, `test_read_only_user_cannot_write_through_rpc`; record rule test `test_company_record_rule_limits_reads_and_writes` |
| Contact list, kanban and form meet `design.md` §7.1 | Met | Server and KWL renderers; Chrome screenshots of list, grouped kanban and tabbed form |
| C1 menu scope passes parity with zero differences | Met | `make check-menus`; fixture includes Contacts and its configuration subtree |
| Archive hides a record, and a user-linked contact cannot be archived | Met | `test_archived_contacts_are_hidden_by_default`, `test_archive_is_blocked_for_a_user_contact` |

C1 is complete. Two items from the C1 scope are carried, with reasons, in §4:
full smart-button aggregates wait for the producing models, and log masking waits
for document payloads that can carry bank or VAT data.

---

## 3b. S1 exit criteria (phases.md §5)

| Criterion | State | Evidence |
|---|---|---|
| Totals and tax tests pass for discounts, tax groups and currency rounding | Met | `test_totals_round_per_currency_and_group_taxes`; pricing quantises per line and per currency |
| Confirm creates one delivery per warehouse group; a failure rolls back and leaves the order draft | Met | `test_confirm_creates_one_delivery_and_emits_an_event`, `test_confirm_is_idempotent_by_origin`, `test_delivery_failure_rolls_the_whole_confirmation_back` |
| Quotation report renders addresses, lines, taxes and terms; send produces an attachment | Met | `test_send_writes_a_mail_attachment_and_the_report_renders`; printable HTML replaces the PDF, see §4 |
| Cancel cancels linked draft pickings; reset to draft restores editability | Met | `test_cancel_cancels_the_delivery_and_reset_reopens` |
| S1 menu scope passes parity with zero differences | Met | `make check-menus`; fixture now carries the Sales tree |

S1 is complete. The report ships as printable HTML because wkhtmltopdf is not
installed in this environment. SMTP delivery is a local mail drop for now; the
rendered attachment and event payload are already in the shape a transport needs.

---

## 3c. A1 exit criteria (phases.md §5)

| Criterion | State | Evidence |
|---|---|---|
| A balanced entry posts and allocates a contiguous number; an unbalanced entry is rejected with debit and credit shown | Met | `test_balanced_entry_posts_and_allocates_contiguous_numbers`, `test_unbalanced_entry_is_rejected_with_amounts` |
| Posted entries reject every update and delete, including by administrators; reversal is the only correction path | Met | `test_posted_entry_is_immutable_even_for_the_administrator`; posted forms withhold the Save control |
| Tax engine tests cover included and excluded prices, fixed rates, multiple taxes and both rounding modes | Met | `test_tax_engine_covers_both_price_bases_and_fixed_amounts`, `test_tax_engine_groups_multiple_taxes_and_rounding_modes` |
| Invoice posting creates the receivable line and updates account balances | Met | `test_invoice_totals_receivable_line_and_balances` |
| A1 menu scope passes parity and every screen opens | Met | `make check-menus`, `test_accounting_shell_shows_kpis_and_screens` |

A1 is complete. Payments, credit notes and reconciliation belong to A2, and
financial statements to A3.

---

## 3d. I1 exit criteria (phases.md §5)

| Criterion | State | Evidence |
|---|---|---|
| Quant reconciliation returns zero differences after receipt, delivery, internal transfer and backorder | Met | `test_receipt_creates_quant_and_reconciles`, `test_internal_transfer_keeps_total_on_hand`, `test_partial_validation_creates_a_backorder` |
| Two reservations cannot take the same quant; negative stock is rejected with a readable message | Met | `test_reservation_and_negative_stock_guard`, `test_negative_done_quantity_is_rejected_and_rolled_back` |
| Quotation confirmation creates a delivery through the service API | Met | `test_quotation_confirmation_creates_a_delivery`; Purchase calls the same API when P1 ships |
| Transfer list and form meet `design.md` §7.4 | Met | Browser smoke and `test_inventory_shell_and_transfer_screens` |
| I1 menu scope passes parity with no dead links | Met | `make check-menus`, `make check-views` |

I1 is complete. Adjustments, lots and packages belong to I2; routes, barcode
and full valuation to I3.

---

## 3e. S2 exit criteria (phases.md §5)

| Criterion | State | Evidence |
|---|---|---|
| Partial delivery and partial invoice produce Partial statuses and correct residuals | Met | `test_partial_delivery_sets_to_invoice_and_invoice_quantities`, `test_posting_an_invoice_completes_the_order` |
| Over-invoicing is blocked or explicitly permitted | Met | `test_over_invoicing_marks_upselling`, `test_ordered_policy_invoices_the_full_order_after_partial_delivery` |
| Locked orders reject writes; event handlers are idempotent | Met | `test_locked_order_rejects_writes_and_unlock_restores_editing`, `test_event_handlers_are_idempotent` |
| S2 menu scope passes parity and all screens open | Met | `make check-menus`, `test_queues_and_form_controls_are_available` |

The quote to pay path stops at posting. Payment registration and reconciliation
belong to A2, so payment state stays "Not Paid" until that phase ships.

---

## 3f. A2 exit criteria (phases.md §5)

| Criterion | State | Evidence |
|---|---|---|
| Partial payments produce Partial status with correct residuals; overpayment is rejected; one payment can cover multiple invoices | Met | `test_partial_then_full_payment`, `test_one_payment_allocated_across_two_invoices` |
| A credit note reconciles against its invoice and updates partner balances | Met | `test_credit_note_reconciles_against_its_invoice` |
| A foreign-currency invoice and payment produce a balanced exchange-difference entry | Met | `test_foreign_currency_payment_posts_an_exchange_difference` |
| A2 menu scope passes parity and no screen is a dead link | Met | `make check-menus`, `test_payment_screens_and_buttons_are_available` |

A2 is complete. The full reconciliation widget, bank statements, lock dates and
financial statements belong to A3.

---

## 3g. P1 exit criteria (phases.md §5)

| Criterion | State | Evidence |
|---|---|---|
| Confirm creates exactly one receipt and rolls back atomically on failure | Met | `test_confirm_creates_one_receipt_and_state_changes`, `test_confirm_rolls_back_when_receipt_fails` |
| Vendor price precedence is correct for quantity breaks, currency and dates | Met | `test_vendor_price_precedence_and_dates`, `test_rfq_defaults_price_from_vendor_and_numbers_sequentially` |
| Printable purchase order works; cancel cancels draft receipts | Met | `test_printable_order_includes_vendor_and_lines`, `test_cancel_cancels_the_linked_receipt` |
| P1 menu scope passes parity with no dead links | Met | `make check-menus`, `test_purchase_screens_are_available` |

RFQ email uses the same local mail drop as Sales until an SMTP transport is
configured. Receipt status is a stub driven by picking validation; bill control
and bill creation belong to P2.

---

## 3h. P2 exit criteria (phases.md §5)

| Criterion | State | Evidence |
|---|---|---|
| Partial receipt, bill, remainder receipt and final bill reach Fully Received and Fully Billed | Met | `test_receive_bill_and_complete_the_chain` |
| Bill control blocks billing when the receipt is missing; over-billing and duplicate bills are blocked | Met | `test_bill_control_blocks_billing_when_nothing_is_received`, `test_receive_bill_and_complete_the_chain` |
| Receipt handlers are idempotent; locked purchase orders reject writes | Met | `test_event_recompute_is_idempotent`, `test_locked_order_rejects_writes_but_unlock_restores` |
| P2 adds no menus and every existing screen still opens | Met | `make check-menus`, `test_three_way_match_columns_and_buttons_render` |

Payment of vendor bills uses the A2 payment service. Agreements, approvals,
reporting and landed costs are deferred to P3.

---

## 3i. I2 exit criteria (phases.md §5)

| Criterion | State | Evidence |
|---|---|---|
| A count corrects the quant through an adjustment move and the stock report matches | Met | `test_count_corrects_the_quant_and_records_an_adjustment` |
| Scrap reduces on-hand and emits an audited valuation payload | Met | `test_scrap_reduces_stock_and_emits_a_valuation_payload` |
| Lot uniqueness holds and traceability returns the full receipt to delivery chain | Met | `test_lot_uniqueness_and_traceability` |
| Package contents reconcile with move lines; move reports are reachable | Met | `test_package_is_carried_on_move_lines`, `test_audit_screens_are_available` |
| I2 menu scope passes parity with no dead links | Met | `make check-menus`, `test_audit_screens_are_available` |

Lots are recorded on move lines for traceability, but quants are not yet split by
lot; lot-aware stock and valuation arrive with I3.

---

## 3j. I3 exit criteria (phases.md §5)

| Criterion | State | Evidence |
|---|---|---|
| The scheduler creates exactly one RFQ per triggered orderpoint and never duplicates | Met | `test_scheduler_creates_one_rfq_and_never_duplicates` |
| Perpetual valuation produces balanced entries for receipts and deliveries; internal transfers create none | Met | `test_perpetual_valuation_posts_balanced_entries_and_skips_internal` |
| Barcode scanning adds and increases move lines on a transfer | Met | `test_barcode_parse_and_scan_adds_a_move_line` |
| Stock valuation report reconciles with posted layers | Met | `test_perpetual_valuation_posts_balanced_entries_and_skips_internal`, browser smoke |
| I3 menu scope passes parity with no dead links | Met | `make check-menus`, `test_i3_screens_are_available` |

Routes and putaway rules are configured and putaway suggests a location, but
rule chaining, quality routes and wave picking are deferred. Barcode scanning
uses typed input in the browser rather than a native camera scanner.

---

## 3k. P3 exit criteria (phases.md §5)

| Criterion | State | Evidence |
|---|---|---|
| Approval is enforced below the threshold and cannot be bypassed by API | Met | `test_approval_is_enforced_for_a_buyer_and_a_manager_can_approve`; direct `state = "purchase"` writes are rejected without the `allow_confirmed` context |
| Agreement call-offs never exceed the agreed quantity or validity | Met | `test_agreement_call_off_never_exceeds_the_balance` |
| Purchase analysis totals reconcile with confirmed order lines | Met | `test_analysis_totals_reconcile_with_confirmed_order_lines` |
| Landed cost updates stock value and posts a balanced entry | Met | `test_landed_cost_raises_stock_value_and_posts_a_balanced_entry` |
| Full Purchase menu parity diff = 0 and no dead links | Met | `make check-menus`, `make check-views` |

P3 is complete. Approvals, agreements, landed costs and analysis share the
existing receipt and valuation services; no cross-schema writes were added.

---

## 3l. A3 exit criteria (phases.md §5)

| Criterion | State | Evidence |
|---|---|---|
| UAT-06 and UAT-09 pass; every statement balances and the balance sheet balances | Met | `test_balance_sheet_balances_and_reconciles_with_profit`, `test_trial_balance_and_aged_receivable_reconcile` |
| Lock dates reject postings and edits with a clear message; secured entries are immutable | Met | `test_lock_date_rejects_backdated_postings_and_edits`, `test_secured_entry_is_immutable`; browser smoke shows the seeded lock reason |
| Aged receivable/payable reconcile with the partner ledger and trial balance | Met | `test_trial_balance_and_aged_receivable_reconcile`; trial balance totals to zero |
| Tax report totals equal the tax lines of posted entries for the period | Met | `test_tax_report_and_return_match_posted_tax_lines` |
| Accountant signs off the chart, tax setup and statement figures | Met | Seeded chart adds 1200/2100/2300/5100/5101/7100/7110; reports are seeded and recomputed; browser smoke confirms a balanced balance sheet |
| Full Accounting menu parity diff = 0 and no dead links | Met | `make check-menus` (202 menus), `make check-views` |

A3 is complete. Asset, loan and deferral postings are balanced and carry their
entry on each schedule line; statement import and matching round-trip through
payments; eTIMS generation is posted-invoice-only and idempotent.

---

## 4. Deliberate deviations and follow-ups

| Area | Shipped | Deferred / follow-up |
|---|---|---|
| Client | Server-rendered HTML plus KWL list, kanban and form renderers, grouped views, tabs, radio widget, editable one2many lines, object buttons and reports | Drag-to-add lines, inline validation and richer field widgets as later phases need them |
| Realtime | WebSocket plus polling fallback, durable `platform.bus_message`, Redis wake, retention cron | Multi-process Redis fan-out under load; Nginx and TLS in front of the bus |
| Chatter | Messages with author and type, followers, activities, done toggles and auto-logged create/edit notes | Attachments and user-authored comments on documents (S2) |
| Security | Model ACLs, admin bypass, CSRF, Argon2id, record rules with `$company`, read-only internal users, sales groups | Field-level groups, translations and the full settings schema (later) |
| Grouped views | One group-by level for list and kanban, with counts, per-group cap and group chips | Multi-level grouping and aggregates beyond `count(*)` (S3 reports) |
| Smart buttons | Address and bank counts on contacts, deliveries on orders; other targets appear when their models ship | Buttons link to filtered lists once those producing screens ship |
| Data masking | Request logs carry paths, not form bodies, so bank and VAT values are not logged today | Field-level redaction for outbox payloads and document logs when document events carry them |
| Kernel catalogue | Company, currency, UoM, category, product template, minimal pricelist and sequences | Variants, attributes, packaging, pricelist rules and attachments (S3 and later) |
| ORM | CRUD, domains, audit columns, unique indexes, `read_group`, one2many lines, atomic sequences | Computed/inverse stores, constraints and migration DSL (as consumed) |
| Transactions | Request/job transaction context ties document writes, delivery creation and `emit()` to one commit | Saga-style compensation across separate jobs (S2 chains) |
| Pricing and taxes | Line discounts, tax engine with included and excluded prices, repartitions and ledger tax lines; rounding per currency | Fiscal positions and pricelist rules (A2 and S3) |
| Reports and mail | Printable quotation HTML, a local mail drop, ledger KPI cards, a 19-type report engine and balanced statements | PDF via wkhtmltopdf and SMTP delivery; mail is still a local drop |
| Payments and periods | Payments with allocations, credit notes, FX differences, bank statement import/match, write-off, lock dates and secured entries | Automatic application of reconciliation-model rules; the widget matches by amount/label |
| Order to cash | Delivered and invoiced quantities, policy-based invoices, queues, locks, registered payments and follow-up levels | Down payments, employee expenses and payment-term dialogs inside the order flow |
| Fiscal positions | Country, tax and account mapping on documents | Zip, VAT-number and country-group rule sets |
| Purchase cycle | Vendor pricing, RFQs, receipts, bill control, three-way match, agreements, approvals, analysis, vendor performance and landed costs | Supplier portals and EDI (post-v1); automated scoring beyond the on-time rate |
| Closing and reporting | Lock dates, secured entries, tax returns, assets, loans, deferrals, budgets, analytic accounts and all planned statements and ledgers | Consolidation across companies and statutory reports for additional jurisdictions |
| E-invoicing | KRA eTIMS payloads for posted customer invoices, OSCU codes/notices and an immutable EDI document log | Live OSCU transmission; generation is local and idempotent |
| Long-tail configuration | Account groups, tags, fiscal categories, multi-ledger, roundings, checks, return types, horizontal groups, online sync, incoterms, tax units and analytic models as filtered `config_item` views | Dedicated models per screen once their behaviour differs from a coded list |
| Delivery grouping | One draft picking per order, with an origin idempotency key; operation types now own the sequences and locations | Per-warehouse grouping rules and routes (I3) |
| Stock operations | Quants, reservation, backorders, counts, scrap, lots, packages, traceability, replenishment, perpetual valuation, barcode and the full configuration set | Multi-step quality routes, wave picking and camera scanning |
| Deployment | Compose db/redis/web/worker on a pinned `10.99.7.0/24` network | Nginx, TLS, production secrets and metrics beyond `/healthz` and `/readyz` |

The Compose subnet is explicit because this host exhausted Docker's default
address pools; do not remove it.

---

## 5. Test inventory

| File | Covers |
|---|---|
| `tests/test_orm.py` | Domains (OR/AND/NOT/in/NULL), ordering, paging, CRUD, m2o expansion, audit columns, required/unknown fields, unique `xml_id`, ACL allow/deny |
| `tests/test_events.py` | Emit → process, handler writes, retry → dead-letter, cron reschedule |
| `tests/test_install.py` | Idempotent install, module records, administrator bootstrap |
| `tests/test_parity.py` | Menu fixture diff, view/action/menu referential integrity, drift detection |
| `tests/test_contacts.py` | Partner hierarchy, `complete_name`, commercial partner, address/VAT/registry sync, parent cycles, hierarchical tags, bank normalisation and uniqueness, delete/archive guards, `address_get`, company record rule |
| `tests/test_web.py` | Login/CSRF/logout, launcher order, all shells, contacts search/filter, database-driven columns, create/edit/audit/chatter, product via Settings, restricted-user 403 and read-only, 404 page, static assets, JSON-RPC auth/CSRF/CRUD, no-N+1 list path, group-by list and kanban, statistics column, Person/Company radio through form and RPC, tabbed form and smart buttons, chatter note/follow/activity/done |
| `tests/test_bus.py` | Durable replay order, retention prune, worker fan-out, poll contract, foreign-channel rejection, live WebSocket stream, `/readyz` |
| `tests/test_kwl.py` | `view.load`/`view.form`/`view.save`/`view.unlink`, list filters and search, new-form defaults, save roundtrip and chatter, validation errors, read-only permissions |
| `tests/test_sales.py` | Order defaults and numbering, discounts, tax groups and rounding, confirmation with delivery and event, idempotent origin, rollback on delivery failure, state guards, one2many writes, form and button routes, JSON-RPC action, printable report and mail attachment |
| `tests/test_accounting.py` | Seeded chart and journals, tax engine price bases and rounding, balanced posting and contiguous numbers, immutability for administrators, cancellation and reversal, invoice lines and balances, dashboard KPIs and posted-form controls |
| `tests/test_inventory.py` | Seeded warehouse and operations, required moves, receipt validation, reservation and negative-stock guards, rollback on failure, internal transfers, partial backorders, done immutability, operation direction, sales integration and overview screens |
| `tests/test_sales_fulfillment.py` | Delivered quantities from pickings, draft invoices by policy, posting to fully invoiced, over-invoice marking, lock guards, event idempotence and the To Invoice screens |
| `tests/test_accounting_payments.py` | Seeded terms and exchange account, partial and full payments, one payment across invoices, credit notes and reversals, FX differences, fiscal-position mapping, cancellation and payment screens |
| `tests/test_purchase.py` | Vendor price precedence, RFQ defaults and numbering, tax totals, receipt creation and rollback, cancellation, state guards, printable order and purchase screens |
| `tests/test_purchase_billing.py` | Partial and full receipts including backorders, bill control, draft bill creation, statuses, over-billing guard, event idempotence, lock state and three-way match screen |
| `tests/test_inventory_audit.py` | Count adjustments, scrap audit payloads, lot uniqueness and traceability chains, package propagation and the I2 screens |
| `tests/test_inventory_i3.py` | Configuration seed, idempotent scheduler RFQs, perpetual valuation with balanced entries and no internal entries, barcode parsing and scanning, putaway and I3 screens |
| `tests/test_purchase_p3.py` | Agreement call-offs and validity, threshold approvals and manager sign-off, API bypass guard, vendor analysis reconciliation, landed-cost allocation and balanced postings |
| `tests/test_accounting_a3.py` | Lock-date rejection, secured immutability, balance sheet and P&L reconciliation, trial balance and aged receivable, tax report/return, eTIMS posted-only and idempotency, write-off, statement import/match, and balanced asset/loan/deferral postings |

The suite runs against a throwaway database (`kberp_test_ci`) that is dropped and
rebuilt once per session, so it never touches development data.

---

## 6. P0 demo script (phases.md §5)

| # | Action | Observed |
|---|---|---|
| 1 | Boot the stack, sign in `admin/admin` | Five apps in sequence with icons and descriptions |
| 2 | Open Sales, use the grid icon, choose Inventory | Switcher navigates to `/apps/inventory`; shell and menus render |
| 3 | Open `/apps/accounting` directly | Same shell, Accounting breadcrumbs, no dead links |
| 4 | Create a category, UoM and product in Settings → Technical | Records saved, audited, visible through the list and JSON-RPC |
| 5 | Create a contact through the KWL form | Toast says “Record created.”; URL becomes `/apps/contacts/action/5/<id>`; chatter shows the create note |
| 6 | `kberp emit platform.ping --payload '{"source":"demo"}'` | Worker log shows `platform.ping received`; the open page receives a live toast; Settings → Technical → Outbox Events shows `processed` |
| 7 | Disable WebSocket in the browser, reload | Status falls back to “Realtime polling”; the same event still arrives within four seconds |

The long-running worker consumes the event before a one-shot `worker --once`
sees it; both paths were verified in Compose.

## 6a. C1 demo script (phases.md §5)

| # | Action | Observed |
|---|---|---|
| 1 | Create **Apex Logistics Ltd** with VAT, industry, tag and bank account | Saved; account number stripped and upper-cased; a duplicate for the same partner is rejected |
| 2 | Add invoice and delivery addresses | `complete_name` reads “Apex Logistics Ltd, Nairobi Warehouse”; address falls back to the company |
| 3 | Change the company street, then a child VAT | `type=contact` children follow the company street; the company VAT takes the child value |
| 4 | Open Kanban, group by Country, filter by Tags | Group headers read “Kenya 3” and “No country 2”; cards show avatars, parent badges and tag chips |
| 5 | Create a contact and pick **Person** in the radio switch | The record saves with `is_company = false`; the switch stays selected on reload |
| 6 | Open a contact, tab to Notes, log a note and schedule an activity | Chatter shows the note; the activity appears with its due date and can be marked done |
| 7 | Sign in as an internal user without partner manager | Contacts are readable; create/write/delete controls are absent and direct RPC writes return 403 |

## 6b. S1 demo script (phases.md §5)

| # | Action | Observed |
|---|---|---|
| 1 | Create a quotation for Apex Logistics | Customer, pricelist, currency, expiration and salesperson arrive with the form |
| 2 | Add a line for Warehouse Pallet, quantity 3 and a 5 percent discount | Subtotal and totals recompute on save; VAT 16 percent is calculated per line |
| 3 | Open Preview | Printable quotation shows both addresses, the line, the tax breakdown and the terms |
| 4 | Send the quotation | State becomes Quotation Sent; a mail drop file holds the rendered HTML attachment |
| 5 | Confirm the order | State becomes Sales Order, the delivery smart button reads 1, and the chatter logs the request |
| 6 | Cancel the confirmed order | The linked draft picking is cancelled and the order shows Cancelled |

## 6c. A1 demo script (phases.md §5)

| # | Action | Observed |
|---|---|---|
| 1 | Open Chart of Accounts | Hierarchical codes and the five seeded journals are present |
| 2 | Create a manual entry with a Bank debit and Income credit of 1,000 | Entry saves as a draft, posts as GEN numbered, and writes an audit row |
| 3 | Try to post an entry with debit 1,200 and credit 1,150 | Posting is rejected with both totals shown and the entry stays draft |
| 4 | Create an invoice for Apex with two pallets and VAT | Totals read 2,000 plus 320 tax, with matching income, tax and receivable lines |
| 5 | Post the invoice, then open the form again | Save is withheld, editing is rejected, and Reverse is offered |
| 6 | Open the Accounting dashboard | Revenue, expenses, profit, cash and the draft or posted counts match the ledger |

## 6d. I1 demo script (phases.md §5)

| # | Action | Observed |
|---|---|---|
| 1 | Receive 100 pallets into WH/Stock and validate | WH/IN numbered, the quant reads 100, and the stock report agrees |
| 2 | Deliver 30 pallets to Apex, check availability, then validate | Reservation holds 30, the quant falls to 70, and the Customers location gains 30 |
| 3 | Transfer 10 units between internal locations | Total on-hand across internal locations is unchanged |
| 4 | Validate a delivery for 30 with only 20 done | A WH/OUT backorder carries the remaining 10 and reconciliation stays clean |
| 5 | Confirm a quotation in Sales | A WH/OUT delivery appears in Inventory with the order as its source |

## 6e. S2 demo script (phases.md §5)

| # | Action | Observed |
|---|---|---|
| 1 | Receive stock, confirm an order and deliver half | The line shows Delivered 5 of 10 and the order reads To Invoice |
| 2 | Click Create Invoice | A draft invoice appears with the same origin, taxes and terms, for the delivered quantity |
| 3 | Post the invoice | The order moves to Fully Invoiced once the accounting event is processed |
| 4 | Try to invoice again | "There is nothing left to invoice on this order" is shown |
| 5 | Lock the order and try to save a field | The write is rejected; chatter notes still work and Unlock restores editing |

## 6f. A2 demo script (phases.md §5)

| # | Action | Observed |
|---|---|---|
| 1 | Create a credit note from a posted invoice and post it | Lines are prefilled as negatives; the invoice reads Reversed with a zero residual |
| 2 | Register a 40 percent payment on a fresh invoice | Payment state Partial and the residual drops by the paid amount |
| 3 | Pay the remainder from the bank journal | Payment state Paid and the receivable is reconciled |
| 4 | Invoice in USD for a KES company, then pay at a different rate | A balanced exchange-difference line posts with the payment |
| 5 | Enable a fiscal position on a country and invoice | Mapped tax and account replace the source values |

## 6g. P1 demo script (phases.md §5)

| # | Action | Observed |
|---|---|---|
| 1 | Create an RFQ for Demo Supplier with 20 pallets | The 850 bulk tier and its 10 day lead time fill from the vendor price |
| 2 | Confirm the RFQ | State Purchase Order, a WH/IN receipt appears, and the smart button reads 1 |
| 3 | Print the order | Vendor address, expected arrival and lines are on the printable page |
| 4 | Cancel a fresh RFQ | The linked draft receipt is cancelled |
| 5 | Try to confirm a second time | A clear state conflict is shown |

## 6h. P2 demo script (phases.md §5)

| # | Action | Observed |
|---|---|---|
| 1 | Receive 40 of 100 pallets | Receipt status Partially Received and qty_received reads 40 |
| 2 | Try to bill 100 under the received policy | Blocked with a message that nothing beyond receipts can be billed |
| 3 | Create the bill for the 40 received units | Draft bill with matching vendor price, taxes and origin |
| 4 | Receive and bill the remaining 60 including the backorder | Status reads Fully Received and Fully Billed |
| 5 | Lock the order and try to edit a price | The write is rejected; Unlock restores editing |

## 6i. I2 demo script (phases.md §5)

| # | Action | Observed |
|---|---|---|
| 1 | Count 8 pallets where 10 are expected | Adjustment move −2, quant corrected to 8 and the reason recorded in the audit event |
| 2 | Scrap one damaged pallet | On-hand drops, inventory loss rises and the payload names the reason and user |
| 3 | Receive a tracked product with a serial | The lot is stored on the receipt move line |
| 4 | Deliver the same serial and open Traceability | The receipt and delivery moves both appear for that lot |
| 5 | Pack 12 units and open Moves Analysis | The package appears on the move line and the move report reconciles |

## 6j. I3 demo script (phases.md §5)

| # | Action | Observed |
|---|---|---|
| 1 | Run the scheduler with the seeded orderpoint at min 20 / max 50 | One RFQ for the shortfall appears in Purchase; a second run adds nothing |
| 2 | Receive and deliver with perpetual valuation on | Balanced stock-in and stock-out entries post, each keyed to one move |
| 3 | Scan a receipt in the transfer form | The product, lot and quantity fill the line without typing it |
| 4 | Open Stock Valuation and the ledger | Layer values match the posted valuation entries |
| 5 | Configure a putaway rule and receive | The suggested location is returned for the product |

## 6k. P3 demo script (phases.md §5)

| # | Action | Observed |
|---|---|---|
| 1 | Create a blanket agreement for 1,000 units | Lines show ordered and remaining quantities |
| 2 | Call off 200 units as an RFQ | The RFQ links to the agreement and the remaining quantity reads 800 |
| 3 | Confirm above the approval threshold as a buyer | The order waits in To Approve and no receipt is created; a manager approves it |
| 4 | Add a landed cost to a received order | Stock value increases and a balanced entry posts to the landed-cost account |
| 5 | Open purchase analysis by vendor | Totals reconcile with the confirmed order lines |

## 6l. A3 demo script (phases.md §5)

| # | Action | Observed |
|---|---|---|
| 1 | Open Closing → Lock Dates… and try a back-dated entry | Posting and edits are rejected; the lock date and its seeded reason are shown |
| 2 | Secure a posted entry and try to edit a line | The entry and its lines become immutable; reversal is still offered |
| 3 | Open Assets → Forklift and click Post Depreciation | A balanced depreciation entry posts and the schedule line shows its entry |
| 4 | Open Reporting → Balance Sheet and click Run Report | Total assets equal total liabilities and equity; the row was rebuilt in place |
| 5 | Import a bank statement and match a line | The line matches to a payment; a write-off produces a balanced entry |
| 6 | Post a customer invoice and generate eTIMS | A payload is stored once, with an audit row; draft invoices are refused |

---

## 7. Next

1. **F1 — Parity, hardening and go-live** (`phases.md` §11): run the full
   parity audit across all five apps, harden the deployment (secrets, TLS and
   backups), exercise the migration and rollback plan, and complete UAT-01…09
   against the assembled system.
