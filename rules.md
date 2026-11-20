# KB ERP — Engineering and Business Rules

| Field | Value |
|---|---|
| Product | **KB ERP** (`kberp`) |
| Version | 1.0 |
| Status | Normative — violations block merge |
| Applies to | Platform + **Contacts, Sales, Purchase, Inventory, Accounting** |
| Companion documents | [`prd.md`](prd.md) · [`architecture.md`](architecture.md) · [`design.md`](design.md) · [`phases.md`](phases.md) |

Rules are identified as `R-<AREA>-<NN>`. Every rule states **how it is enforced**.
If a rule cannot be enforced automatically, it must be checked in code review with a
named reviewer.

---

## 1. How these rules are enforced

| Mechanism | Scope |
|---|---|
| `ruff` + `mypy --strict` | Python style and types |
| `eslint` + `tsc --noEmit` | TypeScript |
| `pytest` unit/integration/contract suites | Behaviour |
| Custom CI script `check-boundaries` | Module imports, schema access, forbidden APIs |
| Custom CI script `check-menus` | Menu parity against `prd.md` §5.2 baseline |
| Custom CI script `check-views` | XML validation, duplicate XML IDs, broken xpath |
| SQL invariant suite | Ledger balance, quant integrity, orphan documents |
| Migration dry-run on staging snapshot | Schema and data safety |
| Code review checklist | Everything not machine-checkable |

No rule may be waived by an individual developer. Exceptions require an ADR and a
written approval from the tech lead; the exception is time-boxed and recorded in
`docs/exceptions.md`.

---

## 2. The ten golden rules

| # | Rule |
|---|---|
| G1 | **One database, five apps, one source of truth per entity.** |
| G2 | **A module writes only its own schema.** Cross-module writes go through services. |
| G3 | **No cross-module imports upward or sideways.** Dependencies follow `architecture.md` §6.2. |
| G4 | **Every document is a state machine.** Transitions are guarded and audited. |
| G5 | **Money is never a float.** Use `Decimal`/`numeric`. |
| G6 | **Posted accounting entries are immutable.** Corrections are reversals. |
| G7 | **Stock is derived from quants, never from a cached number you trust.** |
| G8 | **Server-side validation is mandatory; UI hiding is not security.** |
| G9 | **Every cross-module effect is idempotent and traceable.** |
| G10 | **Menu and label parity with Odoo 19 is a test, not an opinion.** |

---

## 3. Module boundaries and dependencies

### 3.1 Ownership

| Entity | Owner | May be written by |
|---|---|---|
| `core.partner*`, `core.bank`, `core.country*` | base (kernel) | contacts (via kernel service) |
| `core.product*`, `core.uom*`, `core.pricelist*` | base (kernel) | sales/purchase (pricing only, via kernel service) |
| `core.company`, `core.user`, `core.group` | base | auth/admin |
| `sales.*` | sales | sales only |
| `purchase.*` | purchase | purchase only |
| `inventory.*` | inventory | inventory only |
| `accounting.*` | accounting | accounting only |
| `chatter.*` | chatter | chatter service only |
| `platform.*` | base | platform services only |

### 3.2 Dependency rules

| ID | Rule | Enforcement |
|---|---|---|
| R-BND-01 | Dependency graph is a DAG; no cycles | `check-boundaries` computes the closure |
| R-BND-02 | `base` imports no business module | Import scan |
| R-BND-03 | `sales` and `purchase` never import each other | Import scan |
| R-BND-04 | `inventory` never imports `sales` or `purchase`; it may call only `accounting.services.api` for valuation | Import scan |
| R-BND-05 | `accounting` never imports `sales`/`purchase`/`inventory` | Import scan |
| R-BND-06 | `contacts` imports only `base` + `chatter` | Import scan |
| R-BND-07 | A module may import another module's `services/api.py` only | Import scan whitelist |
| R-BND-08 | No imports from another module's `models/` | Import scan |
| R-BND-09 | Schema-qualified SQL may target only the current module's schema, except approved reporting views | SQL linter |
| R-BND-10 | `platform.*` is accessible only through the platform SDK | Import scan |

### 3.3 Allowed cross-module call matrix

| Caller → | core | contacts | sales | purchase | inventory | accounting |
|---|---|---|---|---|---|---|
| core | — | ✘ | ✘ | ✘ | ✘ | ✘ |
| contacts | API | — | ✘ | ✘ | ✘ | ✘ |
| sales | API | API | — | ✘ | API | API |
| purchase | API | API | ✘ | — | API | API |
| inventory | API | ✘ | ✘ | ✘ | — | API (valuation only) |
| accounting | API | API (read) | ✘ | ✘ | ✘ | — |

Reading another module's data for smart buttons is allowed **only** through a
declared query method (`get_statistics`, `get_balance`, `count_documents`), never via
raw SQL.

---

## 4. Cross-module communication

| ID | Rule | Enforcement |
|---|---|---|
| R-COM-01 | Commands that must be atomic use synchronous services in one transaction | Code review + integration tests |
| R-COM-02 | Side effects that may lag use the outbox | `outbox.emit()` required by lint for declared events |
| R-COM-03 | Every event has a versioned schema and a stable name (`<module>.<entity>.<past_tense>`) | Event registry test |
| R-COM-04 | Consumers are idempotent: `consumed_event(event_id, consumer)` unique | DB constraint + test |
| R-COM-05 | Handlers never call back into the producer synchronously | Dependency/direction analysis |
| R-COM-06 | Events are emitted **after** the state change, in the same transaction | Service template + review |
| R-COM-07 | A failed handler is retried with backoff and then dead-lettered | Worker test |
| R-COM-08 | Cross-module payloads contain IDs, not ORM objects | Serializer test |
| R-COM-09 | No cross-module call without `company_id` | Service signature test |
| R-COM-10 | Contracts are append-only; renames require a new method + deprecation | API diff check |

### 4.1 Synchronous vs asynchronous decision table

| Effect | Channel | Reason |
|---|---|---|
| Sale confirm → delivery creation | Sync | Order must not exist without its delivery |
| Sale cancel → delivery cancel | Sync | Consistency of linked documents |
| Purchase confirm → receipt creation | Sync | Same |
| Delivery validate → quant update | Sync | Stock correctness |
| Delivery validate → valuation entry | Sync if perpetual, async if periodic closing | Financial period rules |
| Invoice post → partner totals | Async | Recomputable aggregate |
| Confirm → activity creation | Async | Non-critical side effect |
| Partner change → document display | Async / derived read | Documents reference by id |
| Payment register → invoice payment state | Sync | Money correctness |
| Reordering rule → RFQ suggestion | Async (cron) | Batch process |

---

## 5. Naming conventions

| Item | Convention | Example |
|---|---|---|
| Module | lowercase, singular domain | `sales`, `inventory` |
| Python package | `addons.<module>` | `addons.sales` |
| Model | `<schema>.<snake_case>` | `sales.order_line` |
| Table | same as model, plural discouraged | `inventory.move_line` |
| Field | snake_case | `partner_invoice_id` |
| Boolean field | `is_*`, `has_*`, `use_*` | `is_company`, `has_message` |
| Date field | `date_*` | `date_order`, `date_done` |
| Amount field | `amount_*` | `amount_total`, `amount_residual` |
| Quantity field | `qty_*` or `product_uom_qty` | `qty_delivered` |
| Relational | `<entity>_id`, `<entities>_ids` | `partner_id`, `invoice_ids` |
| XML ID | `<module>.<snake_case>` | `sales.action_quotations` |
| Action path | kebab-case | `requests-for-quotation` |
| Event | `<module>.<entity>.<past_tense>` | `inventory.picking.done` |
| Error code | `<MODULE>_<REASON>` | `SALES_INVALID_STATE` |
| Permission group | `<module>.group_<role>` | `accounting.group_account_manager` |
| Setting key | `<module>.<group>.<name>` | `sales.orders.lock_confirmed` |
| Test | `test_<behaviour>` | `test_confirm_creates_delivery` |

---

## 6. Python rules

| ID | Rule |
|---|---|
| R-PY-01 | Python 3.12; `from __future__ import annotations` not needed; full type hints on public functions |
| R-PY-02 | `mypy --strict` passes for `src/kberp`; `addons/*` type-checked with `--ignore-missing-imports` |
| R-PY-03 | Business logic lives in `services/`, not in models, controllers or XML |
| R-PY-04 | Models may contain field definitions, small computes, constraints and pure helpers |
| R-PY-05 | Services receive and return IDs or typed DTOs, never HTTP objects |
| R-PY-06 | Controllers only authenticate, parse, dispatch, serialize |
| R-PY-07 | No raw SQL outside `orm/` and `report/queries/`; parameterised only |
| R-PY-08 | No `print`; use `structlog` with context |
| R-PY-09 | No mutable default arguments; no `except Exception: pass` |
| R-PY-10 | Transactions are owned by the request/job boundary; services must not commit |
| R-PY-11 | Use `Decimal` for money and quantities; never `float` for stored amounts |
| R-PY-12 | Time: `datetime.now(timezone.utc)`; never naive datetimes |
| R-PY-13 | Raise typed domain errors (`ValidationError`, `AccessError`, `ConflictError`) |
| R-PY-14 | Avoid N+1: use `prefetch`, `select_related`, batched reads |
| R-PY-15 | Public service methods have docstrings with preconditions and side effects |
| R-PY-16 | Feature code is behind module manifests; no conditionals on installed apps in business logic |

### 6.1 Service template

```python
# addons/sales/services/order_service.py
from decimal import Decimal
from kberp.orm import Transaction
from kberp.errors import ValidationError, ConflictError
from addons.inventory.services.api import create_delivery
from addons.sales.services.pricing import compute_totals

def confirm(tx: Transaction, order_id: int, *, user_id: int) -> None:
    """Confirm a quotation.

    Preconditions: state in (draft, sent); at least one line; prices valid.
    Side effects: creates a delivery, emits sales.order.confirmed.
    """
    order = tx.model("sales.order").select_for_update(order_id)
    if order.state not in ("draft", "sent"):
        raise ConflictError("SALES_INVALID_STATE", state=order.state)
    if not order.order_line:
        raise ValidationError("SALES_EMPTY_ORDER")
    compute_totals(tx, order)
    picking = create_delivery(tx, order, user_id=user_id)
    order.write({"state": "sale", "date_order": tx.now(), "delivery_ids": picking.ids})
    tx.chatter.log_state(order, "Quotation", "Sales Order", user_id=user_id)
    tx.outbox.emit("sales.order.confirmed", {
        "order_id": order.id,
        "partner_id": order.partner_id.id,
        "company_id": order.company_id.id,
        "line_ids": order.order_line.ids,
    })
```

---

## 7. TypeScript / KWL rules

| ID | Rule |
|---|---|
| R-TS-01 | Strict TypeScript; no `any` in application code (use `unknown` + narrowing) |
| R-TS-02 | Components are pure renderers; data arrives via props/services |
| R-TS-03 | No `fetch` in components; use the RPC/bus services |
| R-TS-04 | No business rules in the client; server is authoritative |
| R-TS-05 | View renderers implement only the declarative view schema |
| R-TS-06 | All user-visible strings go through translation (`_t`) |
| R-TS-07 | State is URL-driven for search/filter/group/page |
| R-TS-08 | Every interactive element is keyboard reachable and has an accessible name |
| R-TS-09 | No layout shift on load; skeletons for async areas |
| R-TS-10 | Bundle budget: initial backend bundle ≤ 450 KB gzipped |

---

## 8. XML view, menu and action rules

| ID | Rule |
|---|---|
| R-XML-01 | Every view/action/menu/security record has a globally unique XML ID `<module>.<name>` |
| R-XML-02 | Views are extended with `inherit_id` + `xpath`; never copy a base view |
| R-XML-03 | XPath expressions must match exactly one node; load fails otherwise |
| R-XML-04 | No business logic in XML; only structure, labels, modifiers |
| R-XML-05 | `groups` on menus and fields must reference existing groups |
| R-XML-06 | Every action has a stable `path` for deep links |
| R-XML-07 | Menu labels must match `prd.md` §5.2 exactly |
| R-XML-08 | Menu `sequence` gaps of 10 are used to allow insertion |
| R-XML-09 | Form views show errors inline; they do not rely on browser alerts |
| R-XML-10 | A view may reference only fields that exist and are permitted for its groups |
| R-XML-11 | Report templates escape user content; partner data is never marked as safe HTML |
| R-XML-12 | XML files are UTF-8 and must pass `xmllint --noout` |

---

## 9. Business invariants — Contacts

| ID | Invariant | Enforcement | Test |
|---|---|---|---|
| R-CON-01 | A partner is a company, a person, or an address with a company | DB check + service validation | `test_partner_kind` |
| R-CON-02 | `type = contact` requires a non-empty `name` | DB `CHECK` | `test_contact_requires_name` |
| R-CON-03 | Parent hierarchy has no cycles | Recursive check + service guard | `test_no_parent_cycle` |
| R-CON-04 | `commercial_partner_id` is self for companies/roots, else parent's commercial partner | Computed, stored | `test_commercial_partner` |
| R-CON-05 | Address fields sync company ↔ `type=contact` children | Service-level `_fields_sync` | `test_address_sync` |
| R-CON-06 | `vat` syncs up the hierarchy; company registry and industry delegate | Service-level commercial sync | `test_vat_sync` |
| R-CON-07 | `complete_name` = `"Company, Person"`; addresses without a name use their type label | Computed, stored, indexed | `test_complete_name` |
| R-CON-08 | A partner linked to an active user cannot be archived | Service guard | `test_archive_user_partner` |
| R-CON-09 | A partner referenced by any document cannot be deleted | FK `RESTRICT` + service guard | `test_delete_used_partner` |
| R-CON-10 | Bank account number is unique per partner after sanitisation | DB unique constraint | `test_bank_unique` |
| R-CON-11 | Duplicate VAT/registry produces a warning, never a hard block | Warning service | `test_duplicate_warning` |
| R-CON-12 | Archiving hides from selection but keeps document references | Default scope `active = true` | `test_archive_visibility` |

---

## 10. Business invariants — Sales

| ID | Invariant | Enforcement | Test |
|---|---|---|---|
| R-SAL-01 | Only `draft`/`sent` orders can be confirmed | Service guard + `SELECT FOR UPDATE` | `test_confirm_state` |
| R-SAL-02 | Confirming creates exactly one delivery per warehouse group | Service + idempotency key | `test_confirm_delivery` |
| R-SAL-03 | Order totals = sum of line subtotals, discounts and taxes, rounded per currency | Pricing service | `test_totals` |
| R-SAL-04 | `price_unit` comes from the pricelist, then manual override rules | Pricing service | `test_pricelist` |
| R-SAL-05 | `qty_invoiced` never exceeds `qty_ordered` unless the invoice policy allows it | Service guard | `test_over_invoice` |
| R-SAL-06 | `qty_delivered` is updated only by inventory events | Event handler | `test_delivered_event` |
| R-SAL-07 | `invoice_status` derived from quantities and state | Computed | `test_invoice_status` |
| R-SAL-08 | A locked order is read-only except for notes/attachments | Service guard | `test_locked_readonly` |
| R-SAL-09 | Cancel is allowed only from `draft`, `sent`, `sale`; cancels linked pickings that are not done | Service | `test_cancel` |
| R-SAL-10 | One customer invoice per create-invoice call; amounts never exceed the remaining invoiceable amount | Service | `test_invoice_amount` |
| R-SAL-11 | Currency of the order is frozen after confirmation | Service guard | `test_currency_frozen` |
| R-SAL-12 | Deleting a draft order is allowed; confirmed orders are archived/cancelled | Service guard | `test_delete_draft_only` |

---

## 11. Business invariants — Purchase

| ID | Invariant | Enforcement | Test |
|---|---|---|---|
| R-PUR-01 | RFQ can be sent/confirmed only with a vendor and at least one line | Service guard | `test_rfq_required` |
| R-PUR-02 | Approval is required when the total exceeds the threshold and the user lacks manager rights | Service guard | `test_approval_threshold` |
| R-PUR-03 | Confirming creates a receipt per warehouse group | Service + idempotency | `test_confirm_receipt` |
| R-PUR-04 | `qty_received` updated only by inventory events | Event handler | `test_received_event` |
| R-PUR-05 | Bill control policy (ordered/received/received qty) limits billable quantity | Service guard | `test_bill_control` |
| R-PUR-06 | Vendor price selection uses vendor + product + qty + currency + date | Vendor-price service | `test_vendor_price` |
| R-PUR-07 | Currency frozen after confirmation | Service guard | `test_po_currency_frozen` |
| R-PUR-08 | Cancelling a confirmed PO cancels non-done receipts | Service | `test_po_cancel` |
| R-PUR-09 | `receipt_status` and `invoice_status` derived, never manually set | Computed | `test_statuses` |
| R-PUR-10 | Locked PO read-only except notes/attachments | Service guard | `test_po_locked` |

---

## 12. Business invariants — Inventory

| ID | Invariant | Enforcement | Test |
|---|---|---|---|
| R-INV-01 | A move always has product, source location, destination location and quantity > 0 | DB check + service | `test_move_required` |
| R-INV-02 | Quant = sum of done move lines into a location − out of it (per product/lot/owner) | Recompute job + reconciliation query | `test_quant_balance` |
| R-INV-03 | Reservation cannot exceed available quantity unless negative stock is allowed | Reservation service + row locks | `test_reservation` |
| R-INV-04 | Two reservations cannot take the same quant twice | `SELECT FOR UPDATE` on quants | `test_double_reservation` |
| R-INV-05 | Validating a picking writes move lines, updates quants and lots atomically | Single transaction | `test_validate_atomic` |
| R-INV-06 | Done moves are immutable; corrections use reverse moves | Service guard | `test_done_immutable` |
| R-INV-07 | Lots/serials unique per product and company | DB unique constraint | `test_lot_unique` |
| R-INV-08 | A delivery moves to a customer location; a receipt comes from a supplier location | Operation type validation | `test_direction` |
| R-INV-09 | Internal transfers never change total on-hand | Valuation/quant check | `test_internal_no_change` |
| R-INV-10 | Scrap decreases on-hand and is valued | Scrap service | `test_scrap` |
| R-INV-11 | Valuation entries are generated once per done move (idempotent) | Idempotency key `move_id` | `test_valuation_once` |
| R-INV-12 | Negative on-hand is blocked unless the product/company setting allows it | Service guard | `test_negative_stock` |

---

## 13. Business invariants — Accounting

| ID | Invariant | Enforcement | Test |
|---|---|---|---|
| R-ACC-01 | Every posted move has debit total = credit total per company currency | DB trigger + posting service | `test_balance` |
| R-ACC-02 | A posted move is immutable; only reversal creates a new move | DB trigger + service | `test_immutable_posted` |
| R-ACC-03 | Sequence numbers are contiguous per journal/period for posted moves | Sequence service + unique constraint | `test_sequence` |
| R-ACC-04 | Draft moves can be edited or deleted; posted cannot | Service guard | `test_draft_editable` |
| R-ACC-05 | An invoice's `amount_total` = untaxed + taxes, in invoice currency | Tax engine | `test_invoice_totals` |
| R-ACC-06 | Tax lines match the tax repartition lines | Tax engine | `test_tax_repartition` |
| R-ACC-07 | Payment allocation never exceeds the invoice residual | Reconciliation service | `test_overpay` |
| R-ACC-08 | `payment_state` derived from reconciled amounts | Computed | `test_payment_state` |
| R-ACC-09 | `amount_residual` = total − reconciled | Computed/stored | `test_residual` |
| R-ACC-10 | Locked periods reject new postings and edits | Lock-date service | `test_lock_date` |
| R-ACC-11 | Multi-currency entries store company currency and foreign currency amounts plus rate | Posting service | `test_multicurrency` |
| R-ACC-12 | Posted move lines always reference an account of the company | DB check | `test_account_company` |
| R-ACC-13 | Deleting a partner with posted moves is blocked | FK RESTRICT | `test_partner_delete_guard` |
| R-ACC-14 | e-Invoicing payloads are generated only for posted invoices | Adapter guard | `test_edi_posted_only` |

---

## 14. State transition rules

| ID | Rule |
|---|---|
| R-ST-01 | Transitions are implemented as explicit methods (`confirm`, `cancel`, `post`, `validate`), never as raw field writes |
| R-ST-02 | Each transition checks the current state and raises `ConflictError` otherwise |
| R-ST-03 | Each transition writes an audit row and a chatter message |
| R-ST-04 | Each transition is idempotent or explicitly rejects repeats with a clear message |
| R-ST-05 | State fields are `Selection` with the exact labels used in the UI |
| R-ST-06 | Status bar order matches the transition graph in `architecture.md` §12 |
| R-ST-07 | No transition may be triggered by a report or a read |
| R-ST-08 | Bulk transitions run in a job and report per-record failures |
| R-ST-09 | Cancelled documents keep their number; numbers are never reused |
| R-ST-10 | Reopening to draft is allowed only where the business allows it (sales) and never for posted accounting |

---

## 15. Money, quantity and date rules

| ID | Rule | Enforcement |
|---|---|---|
| R-MON-01 | Money stored as `numeric(18,6)`; Python `Decimal` | Schema + lint |
| R-MON-02 | Never compare money with `==` on floats; use quantised values | Lint rule |
| R-MON-03 | Round at currency precision using half-up | Money module |
| R-MON-04 | Store `currency_id` on every amount-bearing document and line | Schema review |
| R-MON-05 | Exchange rates frozen at document date | Service |
| R-QTY-01 | Quantities `numeric(18,6)`, rounded per UoM | Schema + UoM service |
| R-QTY-02 | Never sum quantities across different UoMs | Service guard |
| R-DATE-01 | Business dates are `date`; system timestamps are `timestamptz` UTC | Schema review |
| R-DATE-02 | Accounting period derived from `date`, not `create_date` | Posting service |
| R-DATE-03 | Display in user timezone; never store local time | Serializer |
| R-TZ-01 | Cron schedules stored in UTC with a user/company timezone for display | `ir.cron` |

---

## 16. Security rules

| ID | Rule |
|---|---|
| R-SEC-01 | Every model has explicit ACL rows for every group that can access it; default deny |
| R-SEC-02 | Record rules are additive within a group; global rules always apply |
| R-SEC-03 | Company scoping is enforced by a global rule on every business table |
| R-SEC-04 | Field-level groups are enforced server-side when reading and writing |
| R-SEC-05 | Buttons call services that re-check permissions; hiding a button is not security |
| R-SEC-06 | Export and report endpoints re-check ACL and record rules |
| R-SEC-07 | API keys are hashed, scoped, revocable and rate-limited |
| R-SEC-08 | Passwords use Argon2id with per-user salt; no password is logged |
| R-SEC-09 | Session cookies are `HttpOnly`, `Secure`, `SameSite=Lax`; CSRF token required on writes |
| R-SEC-10 | Sensitive fields (bank numbers, VAT) are masked in logs |
| R-SEC-11 | Administrators cannot edit posted accounting entries |
| R-SEC-12 | The audit log is append-only; no user, including admin, can delete rows |
| R-SEC-13 | Contact creation follows Odoo 19: write access requires `base.group_partner_manager` |
| R-SEC-14 | Permission changes require a reason and are audited |

---

## 17. Import, export and migration rules

| ID | Rule |
|---|---|
| R-IMP-01 | Imports run through the service layer, not raw inserts |
| R-IMP-02 | Import validates required fields, duplicates, country/state consistency and currency |
| R-IMP-03 | Imports are all-or-nothing per batch; failures produce a downloadable error file |
| R-IMP-04 | Import jobs are resumable and idempotent (external key per row) |
| R-IMP-05 | Exports respect ACL/record rules and mask sensitive fields unless permitted |
| R-MIG-01 | Migrations are forward-only and versioned per module |
| R-MIG-02 | Destructive migrations require a backup, a dry run and a rollback plan |
| R-MIG-03 | Data migrations use batched SQL with progress logging |
| R-MIG-04 | Schema changes ship with the module version that needs them |
| R-MIG-05 | No migration may depend on a specific production row id |

---

## 18. Testing rules

| Level | Scope | Gate |
|---|---|---|
| Unit | Pure functions, pricing, taxes, state guards | ≥ 90 % on `services/` and `orm/` |
| Integration | Service + real PostgreSQL + module registry | Every command and state transition |
| Contract | Cross-module APIs and events | Every method in `services/api.py`, every event schema |
| Invariant | SQL checks after scenarios | Ledger balance, quant balance, orphan documents |
| E2E | Launcher → app → document flow | Every UAT script in `prd.md` §11.1 |
| Visual | Key screens snapshots | Launcher, list, form, kanban, statement |
| Performance | Top 20 queries + document posting | Query budget enforced in CI |
| Parity | Menu tree, action labels, settings groups | Compared with baseline |

| ID | Rule |
|---|---|
| R-TST-01 | Tests use factories, never fixture dumps of production data |
| R-TST-02 | Each test creates its own company/partners/products with unique codes |
| R-TST-03 | Time is frozen in tests (`freezegun`) |
| R-TST-04 | No test depends on execution order |
| R-TST-05 | Accounting tests assert both move balance and partner balances |
| R-TST-06 | Inventory tests assert quant before/after and valuation entries |
| R-TST-07 | Cross-module tests assert the emitted outbox events |
| R-TST-08 | Flaky tests are quarantined within 24 h and fixed or deleted |
| R-TST-09 | A bug fix ships with a regression test named after the issue |
| R-TST-10 | Coverage may not decrease on a pull request |

---

## 19. UI parity rules

| ID | Rule |
|---|---|
| R-UI-01 | Menu labels and hierarchy match `prd.md` §5.2; deviations require a product decision |
| R-UI-02 | Each form has the Odoo tab names where the concept exists (Contacts, Sales & Purchase, Invoicing, Notes) |
| R-UI-03 | Smart buttons show the same statistics as Odoo (Invoiced, Vendor Bills, Sales, Purchases, Lots/Serials, Payment Methods) |
| R-UI-04 | State labels match the reference (Quotation, Quotation Sent, Sales Order, Cancelled; RFQ, RFQ Sent, To Approve, Purchase Order) |
| R-UI-05 | Settings groups mirror the reference groups even if some toggles are not yet implemented (they are disabled with a reason) |
| R-UI-06 | Every list supports search, filter, group-by and column selection |
| R-UI-07 | Every document has a chatter with messages and activities |
| R-UI-08 | Keyboard: `Alt+W` app switcher, `Alt+Q` search, `Ctrl+S` save, `Esc` close |
| R-UI-09 | No dead links: a menu either opens an implemented action or is absent |
| R-UI-10 | Empty states explain the next action and link to it |

---

## 20. Performance rules

| ID | Rule | Enforcement |
|---|---|---|
| R-PERF-01 | No endpoint returns more than 5 000 rows | Pagination guard |
| R-PERF-02 | Lists are paginated at 80 by default | Client + server |
| R-PERF-03 | Every FK and every `state`/`date` filter column is indexed | Schema review |
| R-PERF-04 | N+1 queries are forbidden; use prefetch/batched reads | Query count test |
| R-PERF-05 | Report queries run on read replicas or outside request timeouts | Config |
| R-PERF-06 | Document posting ≤ 1.5 s p95 for 50 lines | Benchmark test |
| R-PERF-07 | JSON-RPC payloads ≤ 1 MB; attachments streamed | Middleware |
| R-PERF-08 | Long tasks (> 5 s) run in the worker | Code review |
| R-PERF-09 | Cache invalidation is explicit and versioned | Registry version |
| R-PERF-10 | `EXPLAIN ANALYZE` required for new queries over 100 ms on staging | CI report |

---

## 21. Error handling, logging and audit

| ID | Rule |
|---|---|
| R-ERR-01 | Domain errors use stable codes and human-readable messages with a remediation hint |
| R-ERR-02 | The UI shows field-level errors next to fields and a summary toast |
| R-ERR-03 | Never expose stack traces or SQL to end users |
| R-LOG-01 | Structured logs include `request_id`, `user_id`, `company_id`, `model`, `method`, `duration_ms` |
| R-LOG-02 | Log state transitions at INFO; failures at WARN/ERROR with context |
| R-LOG-03 | Never log passwords, tokens, full bank numbers or personal data bodies |
| R-AUD-01 | Audit: who, when, what changed, from which screen/API, reason when required |
| R-AUD-02 | Audit rows are immutable and retained 10 years |
| R-AUD-03 | Bulk operations write one audit row per affected record |

---

## 22. Documentation rules

| ID | Rule |
|---|---|
| R-DOC-01 | Every module has a README with purpose, models, services, events, menus and settings |
| R-DOC-02 | Every public service method is documented in `services/api.py` |
| R-DOC-03 | Every event is listed in the event catalog (`architecture.md` §10.3) |
| R-DOC-04 | Every setting is listed in `prd.md` §8 with its default |
| R-DOC-05 | Architecture changes update `architecture.md` in the same PR |
| R-DOC-06 | Screenshots in `design.md` are regenerated when the UI changes materially |
| R-DOC-07 | ADRs are added for irreversible or cross-cutting decisions |

---

## 23. Git, review and CI

| ID | Rule |
|---|---|
| R-GIT-01 | Trunk-based development; short-lived branches (`feat/<module>/<topic>`) |
| R-GIT-02 | Conventional commits: `feat(sales): …`, `fix(accounting): …`, `chore: …` |
| R-GIT-03 | One logical change per PR; no mixed refactor + feature |
| R-GIT-04 | PR description states module, requirement IDs, test evidence and screenshots |
| R-GIT-05 | Required checks: lint, types, unit, integration, contract, boundaries, menus, views |
| R-GIT-06 | Two approvals for `accounting` and `inventory` changes; one elsewhere |
| R-GIT-07 | No direct pushes to `main`; no force-push after review |
| R-GIT-08 | Database migrations reviewed by a second engineer |
| R-GIT-09 | Release tags `vX.Y.Z`; changelog generated from commits |
| R-GIT-10 | Rollback plan in the release notes |

### 23.1 CI pipeline

```
1. lint          ruff, eslint, prettier
2. types         mypy, tsc
3. unit          pytest -m unit
4. db up         postgres service container
5. migrate       install all modules into a blank DB
6. integration   pytest -m integration
7. contract      pytest -m contract
8. invariants    SQL checks
9. views/menus   check-views, check-menus (parity baseline)
10. build        vite build, asset manifest
11. e2e          playwright (launcher + UAT-03 + UAT-04)
12. perf         query budget on seed dataset
```

---

## 24. Definition of Done (checklist)

- [ ] Requirement IDs implemented and referenced in the PR.
- [ ] Menu/action path matches the parity baseline.
- [ ] List, form, search views implemented; kanban where required.
- [ ] Server-side validation, ACL and record rules.
- [ ] State transitions guarded, audited and tested.
- [ ] Cross-module calls only through services; events emitted.
- [ ] Idempotency for commands and handlers.
- [ ] Unit + integration + contract tests pass.
- [ ] No new N+1; query budget respected.
- [ ] Translations added.
- [ ] Error messages actionable.
- [ ] Docs updated (`README`, `prd.md` if scope changed).
- [ ] Screenshots for UI changes.
- [ ] Product owner demo passed.

---

## 25. Anti-patterns (reject on sight)

| Anti-pattern | Why | Correct approach |
|---|---|---|
| Importing another module's model class | Breaks boundaries | Call its service API |
| Writing to `sales.order` from `inventory` | Ownership violation | Emit an event; sales consumes it |
| Direct SQL join across schemas in business code | Hidden coupling | Query service or reporting view |
| Business logic in a controller/component | Untestable, insecure | Service layer |
| Storing money as `float` | Rounding errors | `Decimal`/`numeric` |
| Editing a posted journal entry | Audit violation | Reverse and repost |
| Trusting a cached stock number | Overselling | Recompute from quants |
| Catch-all exception handling | Hides defects | Typed errors + logs |
| Copying a view instead of inheriting | Broken upgrades | `inherit_id` + xpath |
| Menu entry without an action or with a dead link | Broken UX | Implement or omit |
| Client-side permission checks only | Security hole | Server checks |
| Emitting events before committing | Phantom events | Emit in the same transaction |
| Non-idempotent event handler | Duplicate documents | `consumed_event` |
| Tests depending on order/seed data | Flakiness | Factories + isolation |
| Silent migration failures | Data corruption | Fail fast, dry run |

---

*End of rules. Continue with [`design.md`](design.md).*
