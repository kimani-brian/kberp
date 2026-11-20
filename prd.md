# KB ERP — Product Requirements Document (PRD)

| Field | Value |
|---|---|
| Product | **KB ERP** (`kberp`) |
| Version | 1.0 (draft for build) |
| Scope | Five applications: **Contacts, Sales, Purchase, Inventory, Accounting** |
| Reference behaviour | Odoo 19 CE/EE, database `newdb`, server `19.0-20260619` |
| Reference stack | Python 3.12 · PostgreSQL 16 · Werkzeug 3 · XML views · OWL-style TypeScript client · Bootstrap 5 |
| Companion documents | [`architecture.md`](architecture.md) · [`rules.md`](rules.md) · [`design.md`](design.md) · [`phases.md`](phases.md) |
| Status | Approved for phase planning |

---

## 1. Vision

Build a self-hosted ERP whose five business applications behave like their Odoo 19
counterparts: the same menus, submenus, form tabs, smart buttons, configuration
screens, document state machines and cross-application flows — but implemented as a
clean, modular Python/PostgreSQL system we own.

The product opens on an **application launcher**: a page with five large icons. Each
icon opens an application with its own menu bar and submenus. Behind the interface the
five applications share one database, one partner directory, one product catalogue and
one accounting ledger, and they exchange documents and events exactly like Odoo's
modules do.

### 1.1 The one-sentence test

> A user can open **Sales**, create a quotation, confirm it, see a delivery appear in
> **Inventory**, create an invoice in **Accounting**, register a payment, and find the
> customer in **Contacts** — without leaving the product or re-entering data.

If that journey works end-to-end, the architecture is correct.

---

## 2. Goals, non-goals and success metrics

### 2.1 Goals

| # | Goal | Measure |
|---|---|---|
| G1 | Five-app launcher and per-app navigation identical in structure to Odoo 19 | Menu tree diff = 0 unintended differences |
| G2 | Shared master data across all apps | One `partner`, one `product`, one `company`, one `currency` |
| G3 | Document flows that cross apps automatically | Quote→Delivery→Invoice→Payment in one flow, no re-keying |
| G4 | Odoo-compatible configuration surface | Each app has **Settings** plus its configuration submenus |
| G5 | Modular monolith with enforceable boundaries | No cross-module table writes; CI boundary check passes |
| G6 | Predictable accounting and stock | Ledger always balanced; stock never negative unless allowed |
| G7 | Auditable | Every document state change is logged with user, time and reason |

### 2.2 Non-goals (v1)

- Website builder, e-commerce front-end, blog, forum, live chat.
- Manufacturing (MRP), quality, maintenance, projects, timesheets.
- Payroll, HR, expenses beyond "employee expense" bills.
- Full Odoo Studio-style customisation, drag-and-drop report designer.
- Marketplace app store, multi-tenant SaaS billing.
- Mobile native apps (responsive web only).

### 2.3 Success metrics

| Metric | Target |
|---|---|
| Menu parity score (labels + hierarchy) | ≥ 95 % of in-scope Odoo menus |
| Quote→cash cycle completed in UAT without manual DB fix | 100 % of scripted cases |
| p95 list-view latency (10k rows, 25 columns) | < 800 ms |
| p95 document post/confirm transaction | < 1.5 s |
| Cross-module event delivery (outbox→consumer) | < 5 s p95 |
| Critical accounting defects at go-live | 0 |
| Accessibility (WCAG 2.2 AA) on launcher + forms | 100 % of audited screens |

---

## 3. Personas and roles

| Persona | Primary apps | Needs |
|---|---|---|
| **Salesperson** | Sales, Contacts | Fast quotation entry, customer history, prices, warnings, "To Invoice" queue |
| **Sales manager** | Sales, Accounting (read) | Teams, targets, margin, confirmation/lock control, discounts |
| **Buyer** | Purchase, Inventory (read) | RFQs, vendor prices, approvals, receipt status |
| **Purchase manager** | Purchase, Accounting (read) | Double validation, agreements, vendor performance |
| **Warehouse operator** | Inventory | Receipts, deliveries, internal transfers, counts, scraps, barcodes |
| **Stock manager** | Inventory, Accounting (read) | Routes, reordering rules, valuation, locations, operation types |
| **Accountant** | Accounting, all apps (read) | Journal entries, invoices, payments, reconciliation, taxes, reports, lock dates |
| **Finance manager** | Accounting | Statements, aged balances, fiscal positions, credit limits |
| **Administrator** | All + Settings | Users, groups, companies, sequences, modules, backups |
| **Auditor (read-only)** | Accounting, Inventory | Traceability, immutable posted entries, audit log |

Role → permission mapping is specified in [`rules.md`](rules.md) §11 and implemented
with ACLs + record rules.

---

## 4. Product scope

### 4.1 Applications (the five icons)

| # | App | Key | Icon concept | Root sequence | Colour accent |
|---|---|---|---|---|---|
| 1 | Contacts | `contacts` | Address book / person card | 20 | Teal |
| 2 | Sales | `sales` | Price tag / rising chart | 30 | Indigo |
| 3 | Accounting | `accounting` | Ledger / scales | 60 | Green |
| 4 | Purchase | `purchase` | Cart / box with arrow in | 135 | Amber |
| 5 | Inventory | `inventory` | Boxes / warehouse | 140 | Blue |

> Launcher order is data-driven from each app's `sequence`, exactly like Odoo's app
> switcher. The table above is the default.

### 4.2 Platform (not shown as icons)

`base` (shared kernel), `web` (shell, view engine), `auth` (users, groups, ACLs),
`bus` (notifications), `mail`-like `chatter` (messages, activities), `report`
(QWeb-style PDF). These are internal modules; they appear under **Settings**.

### 4.3 Module coverage matrix

Every document in this set covers all five apps. This matrix is repeated in each file.

| Capability | Contacts | Sales | Purchase | Inventory | Accounting |
|---|---|---|---|---|---|
| Own menu tree | ✔ | ✔ | ✔ | ✔ | ✔ |
| List / kanban / form / search views | ✔ | ✔ | ✔ | ✔ | ✔ |
| Configuration submenu | ✔ | ✔ | ✔ | ✔ | ✔ |
| Settings screen | ✔ | ✔ | ✔ | ✔ | ✔ |
| Shared partner usage | owns | consumes | consumes | consumes | consumes |
| Shared product usage | — | consumes | consumes | owns stockable part | consumes |
| Creates documents for other apps | — | delivery, invoice | receipt, bill | valuation entries | payments |
| Consumes other apps' documents | — | inventory, accounting | inventory, accounting | sales, purchase | sales, purchase, inventory |
| Background jobs | import/enrich | recurring invoices, quote expiry | receipt reminders, reorder | scheduler, valuation | recurring entries, follow-ups |

---

## 5. Information architecture

### 5.1 Entry and navigation

```
/                          → redirect to /apps
/apps                      → Application launcher (five icons, search, recent)
/apps/contacts             → Contacts app home
/apps/sales                → Sales app home (Orders → Quotations)
/apps/purchase             → Purchase app home
/apps/inventory            → Inventory app home (Overview)
/apps/accounting           → Accounting app home (Dashboard)
/apps/<app>/<action-path>  → A window action, e.g. /apps/sales/quotations
```

Rules:

1. The launcher is the only page without an app menubar.
2. Inside an app, the top bar always shows: app switcher (grid icon), app name,
   menubar, global search, activity bell, user menu.
3. Clicking the grid icon opens the launcher as an overlay; it never reloads the app.
4. Deep links are stable and bookmarkable; the URL is the source of truth.
5. Browser back/forward follows the navigation history.

### 5.2 Menu parity (must match Odoo 19)

The menu trees below are the acceptance baseline. Labels are exact; order follows the
live `sequence` values, with items that share a sequence grouped by function. Empty
parent menus in the reference (no action, no visible children) are omitted.

#### Contacts

```
Contacts
├── Contacts
└── Configuration
    ├── Contact Tags
    ├── Industries
    ├── Localization
    │   ├── Countries
    │   ├── Fed. States
    │   └── Country Group
    └── Bank Accounts
        ├── Banks
        └── Bank Accounts
```

#### Sales

```
Sales
├── Orders
│   ├── Quotations
│   ├── Orders
│   ├── Sales Teams
│   └── Customers
├── To Invoice
│   ├── Orders to Invoice
│   └── Orders to Upsell
├── Products
│   ├── Products
│   ├── Product Variants
│   └── Pricelists
├── Reporting
│   ├── Sales
│   ├── Salespersons
│   ├── Products
│   └── Customers
└── Configuration
    ├── Settings
    ├── Sales Teams
    ├── Sales Orders
    │   ├── Quotation Templates
    │   ├── Headers/Footers
    │   ├── Delivery Methods
    │   └── Tags
    ├── Products
    │   ├── Attributes
    │   ├── Combo Choices
    │   ├── Categories
    │   ├── Product Tags
    │   └── Units & Packagings
    ├── Online Payments
    │   ├── Payment Providers
    │   ├── Payment Methods
    │   ├── Payment Tokens
    │   └── Payment Transactions
    └── Activities
        ├── Activity Types
        └── Activity Plans
```

#### Purchase

```
Purchase
├── Orders
│   ├── Requests for Quotation
│   ├── Purchase Orders
│   ├── Purchase Agreements
│   └── Vendors
├── Products
│   ├── Products
│   └── Product Variants
├── Reporting
│   └── Purchase
└── Configuration
    ├── Settings
    ├── Vendor Pricelists
    └── Products
        ├── Attributes
        ├── Categories
        └── Units & Packagings
```

#### Inventory

```
Inventory
├── Overview
├── Operations
│   ├── Transfers
│   │   ├── Receipts
│   │   ├── Deliveries
│   │   └── Internal
│   ├── Adjustments
│   │   ├── Physical Inventory
│   │   └── Scrap
│   ├── Procurement
│   │   ├── Replenishment
│   │   └── References
│   └── Procurement: run scheduler
├── Products
│   ├── Products
│   ├── Product Variants
│   ├── Lots / Serial Numbers
│   └── Packages
├── Reporting
│   ├── Stock
│   ├── Locations
│   ├── Moves History
│   ├── Moves Analysis
│   └── Performance
└── Configuration
    ├── Settings
    ├── Warehouse Management
    │   ├── Warehouses
    │   ├── Operations Types
    │   ├── Locations
    │   ├── Routes
    │   ├── Rules
    │   ├── Storage Categories
    │   └── Putaway Rules
    ├── Products
    │   ├── Categories
    │   ├── Attributes
    │   ├── Units & Packagings
    │   └── Barcode Nomenclatures
    └── Delivery
        ├── Delivery Methods
        ├── Package Types
        └── Zip Prefix
```

#### Accounting

```
Accounting
├── Dashboard
├── Customers
│   ├── Invoices
│   ├── Credit Notes
│   ├── Payments
│   ├── Products
│   └── Customers
├── Vendors
│   ├── Bills
│   ├── Refunds
│   ├── Customs Imports
│   ├── Payments
│   ├── Employee Expenses
│   ├── Products
│   └── Vendors
├── Accounting
│   ├── Transactions
│   │   ├── Journal Entries
│   │   └── Analytic Items
│   ├── Assets & Liabilities
│   │   ├── Assets
│   │   └── Loans
│   ├── Closing
│   │   ├── Reconcile
│   │   ├── Tax Returns
│   │   ├── Lock Dates…
│   │   └── Secure Entries
│   ├── Review
│   │   ├── Control
│   │   │   ├── Journal Items
│   │   │   └── Journal Audit
│   │   ├── Audit
│   │   │   └── Working Files
│   │   ├── Inventory
│   │   │   ├── Inventory Valuation
│   │   │   ├── Depreciation Schedule
│   │   │   └── Loans Analysis
│   │   ├── Regularization Entries
│   │   │   ├── Unrealized Currencies
│   │   │   ├── Deferred Revenues
│   │   │   └── Deferred Expenses
│   │   ├── Purchases
│   │   │   ├── Billed Not Received
│   │   │   └── Bill To Receive
│   │   ├── Sales
│   │   │   ├── Invoices To Be Issued
│   │   │   └── Invoiced Not Delivered
│   │   └── Logs
│   │       └── Audit Trail
│   ├── Reporting
│   │   ├── Statement Reports
│   │   │   ├── Cash Flow Statement
│   │   │   ├── Balance Sheet
│   │   │   └── Profit and Loss
│   │   ├── Ledgers
│   │   │   ├── Trial Balance
│   │   │   └── General Ledger
│   │   ├── Partner Reports
│   │   │   ├── Partner Ledger
│   │   │   ├── Aged Payable
│   │   │   └── Aged Receivable
│   │   ├── Taxes & Fiscal
│   │   │   ├── Tax Report
│   │   │   ├── EC Sales List
│   │   │   └── Fiscal Report
│   │   └── Management
│   │       ├── Invoice Analysis
│   │       ├── Analytic Report
│   │       └── Executive Summary
│   └── Configuration
│       ├── Settings
│       ├── Accounting
│       │   ├── Chart of Accounts
│       │   ├── Taxes
│       │   ├── Tax Groups
│       │   ├── Tax Units
│       │   ├── Journals
│       │   ├── Fiscal Positions
│       │   ├── Fiscal Years
│       │   ├── Currencies
│       │   ├── Account Groups
│       │   ├── Account Tags
│       │   ├── Fiscal Categories
│       │   ├── Multi-Ledger
│       │   ├── Cash Roundings
│       │   ├── Checks
│       │   ├── Return Types
│       │   ├── Financial Budgets
│       │   ├── Asset Models
│       │   ├── Accounting Reports
│       │   ├── Horizontal Groups
│       │   └── Online Synchronization
│       ├── KRA eTIMS
│       │   ├── KE OSCU Codes
│       │   └── KE OSCU Notices
│       ├── Invoicing
│       │   ├── Payment Terms
│       │   ├── Follow-up Levels
│       │   ├── Incoterms
│       │   └── Product Categories
│       ├── Online Payments
│       │   ├── Payment Providers
│       │   ├── Payment Methods
│       │   ├── Payment Tokens
│       │   └── Payment Transactions
│       └── Analytic Accounting
│           ├── Analytic Distribution Models
│           ├── Analytic Accounts
│           └── Analytic Plans
```

> The `Invoicing` top-level app from Odoo is folded into **Accounting** for a
> five-icon product. All its actions remain reachable (Customers, Vendors,
> Configuration → Invoicing), preserving URL paths such as `/apps/accounting/customers`.
>
> Empty parent menus in the reference database (`Invoicing` app root,
> `Configuration → Assets and Revenues`, `Configuration → Accounting → Reporting`)
> have no action and no visible children, so they are not part of the baseline.

---

## 6. Functional requirements

Requirement IDs are stable and referenced by `phases.md`, `rules.md` and tests.
Priority: **M** = must, **S** = should, **C** = could (v1.x).

### 6.1 Platform / shell

| ID | Priority | Requirement |
|---|---|---|
| FR-PLT-001 | M | `/apps` shows the five applications as a responsive grid of icon cards with name, one-line description and keyboard focus order. |
| FR-PLT-002 | M | Clicking an icon navigates to that app's default action without full page reload. |
| FR-PLT-003 | M | The app switcher overlay is reachable from every screen (`Alt+W` / grid icon) and lists the same five apps plus Settings. |
| FR-PLT-004 | M | Each app renders a menubar from server-provided menu records; submenus open on hover/click and are keyboard navigable. |
| FR-PLT-005 | M | Deep links resolve to the same action, view and record after reload. |
| FR-PLT-006 | M | Global search finds partners, products, sale orders, purchase orders, invoices and pickings, grouped by model. |
| FR-PLT-007 | M | Notifications (bell) show activities and bus messages; unread count persists per user. |
| FR-PLT-008 | M | Every list view supports search, filters, group-by, column choice, pagination and export. |
| FR-PLT-009 | M | Every form view supports breadcrumbs, status bar, smart buttons, chatter and attachment upload. |
| FR-PLT-010 | M | The UI is translatable; all labels come from XML/translation files, none hard-coded in JS. |
| FR-PLT-011 | M | A user with insufficient rights sees the action hidden or gets a readable 403 page. |
| FR-PLT-012 | S | Recent items and favourites appear on the launcher. |

### 6.2 Contacts (`contacts`)

| ID | Priority | Requirement |
|---|---|---|
| FR-CON-001 | M | One partner record can be a **company**, a **person**, or an **address of a company** (`type` = contact/invoice/delivery/other). |
| FR-CON-002 | M | Company/person radio, `parent_id`, `function`, VAT, website, tags, language, address block and country-aware address format. |
| FR-CON-003 | M | A company form shows its child contacts/addresses as a kanban; child creation inherits the company address. |
| FR-CON-004 | M | Address fields sync between a company and its `type=contact` children; VAT syncs up; company registry and industry are delegated. |
| FR-CON-005 | M | `complete_name` displays `"Company, Person"` and drives alphabetical ordering. |
| FR-CON-006 | M | Contact Tags are hierarchical (parent/child tags) and filter lists with `child_of`. |
| FR-CON-007 | M | Industries list is configurable; only companies can select one (view rule). |
| FR-CON-008 | M | Bank accounts per partner, with a bank directory (`res.bank` equivalent), unique account number per partner, BIC uppercase. |
| FR-CON-009 | M | Localization: countries, fed. states, country groups; country drives address format and VAT label. |
| FR-CON-010 | M | Duplicate VAT / company-registry warning with a link to the duplicate; saving allowed. |
| FR-CON-011 | M | Archive instead of delete; deletion blocked when referenced by documents or an active user. |
| FR-CON-012 | M | Chatter: messages, notes, attachments, followers, activities (Call, Email, Meeting, To-Do, Document). |
| FR-CON-013 | M | Import/export with templates and duplicate checks. |
| FR-CON-014 | S | Merge duplicates wizard that re-points documents. |
| FR-CON-015 | S | Geolocation (latitude/longitude) and address autocomplete hook. |
| FR-CON-016 | C | Partner enrichment via external API keys. |

### 6.3 Sales (`sales`)

| ID | Priority | Requirement |
|---|---|---|
| FR-SAL-001 | M | Quotation and sales order with header (customer, invoice address, delivery address, pricelist, payment terms, currency, validity, salesperson, team, tags) and lines (product, description, qty, UoM, price, discount, taxes, subtotal). |
| FR-SAL-002 | M | States `draft → sent → sale → cancel` plus `locked` boolean; status bar mirrors Odoo labels (Quotation, Quotation Sent, Sales Order, Cancelled). |
| FR-SAL-003 | M | Confirm creates delivery(s) via Inventory and makes the order invoiceable. |
| FR-SAL-004 | M | `invoice_status`: Nothing to Invoice / To Invoice / Fully Invoiced / Upselling Opportunity. |
| FR-SAL-005 | M | "Create Invoice" produces a customer invoice in Accounting with the correct lines, taxes, currency and payment terms; supports down-payment invoice. |
| FR-SAL-006 | M | Delivered and invoiced quantities are tracked per line; over-invoicing and over-delivery blocked by settings. |
| FR-SAL-007 | M | Pricelists: currency, fixed/percentage/formula rules, min quantity, date ranges, variant criteria. |
| FR-SAL-008 | M | Taxes computed by Accounting tax engine; tax totals shown per group. |
| FR-SAL-009 | M | Customer warnings (`sale_warn_msg`) shown on quotation confirmation when the group is enabled. |
| FR-SAL-010 | M | Sales Teams with members, targets and assignment; salesperson defaults from the customer. |
| FR-SAL-011 | M | Quotation templates (headers/footers, lines) and optional products. |
| FR-SAL-012 | M | "To Invoice" queues and "Upselling" queue. |
| FR-SAL-013 | M | Reports: Sales, Salespersons, Products, Customers (pivot/graph/list, date and team filters). |
| FR-SAL-014 | S | Credit limit check using Accounting balances + open orders. |
| FR-SAL-015 | S | Online payment / payment link on quotations. |
| FR-SAL-016 | S | Recurring invoices and quote expiry automation. |

### 6.4 Purchase (`purchase`)

| ID | Priority | Requirement |
|---|---|---|
| FR-PUR-001 | M | RFQ and purchase order with vendor, currency, payment terms, delivery date, buyer, incoterm and lines. |
| FR-PUR-002 | M | States `draft → sent → to approve → purchase → cancel` plus `locked`; labels RFQ, RFQ Sent, To Approve, Purchase Order, Cancelled. |
| FR-PUR-003 | M | Confirming creates a receipt in Inventory and makes the order billable. |
| FR-PUR-004 | M | `receipt_status`: Not Received / Partially Received / Fully Received; `invoice_status`: Nothing to Bill / Waiting Bills / Fully Billed. |
| FR-PUR-005 | M | "Create Bill" produces a vendor bill in Accounting with matching lines; 3-way match control policy (ordered / received / received+received qty). |
| FR-PUR-006 | M | Vendor pricelists (supplierinfo): vendor, product, price, min qty, currency, lead time. |
| FR-PUR-007 | M | Purchase Agreements / blanket orders with call-offs. |
| FR-PUR-008 | M | Vendor warnings, receipt reminder email and days-before setting. |
| FR-PUR-009 | M | Double validation / approval threshold for managers. |
| FR-PUR-010 | M | Reports: Purchase analysis by vendor, product, category, date. |
| FR-PUR-011 | S | Vendor on-time rate and purchase line suggestions. |
| FR-PUR-012 | S | Customs imports and landed costs. |

### 6.5 Inventory (`inventory`)

| ID | Priority | Requirement |
|---|---|---|
| FR-INV-001 | M | Warehouse, location tree with usages (internal, supplier, customer, inventory, production, transit), operation types. |
| FR-INV-002 | M | Receipts, deliveries and internal transfers with moves, move lines, reservation and validation. |
| FR-INV-003 | M | Move states `draft → waiting → confirmed → partially_available → assigned → done / cancel`; picking states mirror Odoo. |
| FR-INV-004 | M | On-hand quantities per product/location/lot/owner (`quants`); stock report and location report. |
| FR-INV-005 | M | Physical inventory count and scrap with adjustment moves. |
| FR-INV-006 | M | Lots/serials and packages; traceability from receipt to delivery. |
| FR-INV-007 | M | Routes and rules: buy, make-to-order, drop-ship, cross-dock; reordering rules (min/max) and scheduler. |
| FR-INV-008 | M | Valuation: periodic (manual closing) and perpetual (automatic journal entries) modes; stock valuation report. |
| FR-INV-009 | M | Barcode nomenclature and scan-to-transfer. |
| FR-INV-010 | M | Reports: Stock, Locations, Moves History, Moves Analysis, Performance. |
| FR-INV-011 | M | Sales and purchase integrations create/consume pickings through services, not direct DB writes. |
| FR-INV-012 | S | Putaway rules, storage categories, package types, delivery methods. |
| FR-INV-013 | C | Multi-step routes (input → quality → stock → output). |

### 6.6 Accounting (`accounting`)

| ID | Priority | Requirement |
|---|---|---|
| FR-ACC-001 | M | Chart of accounts (hierarchical codes), journals (sale, purchase, bank, cash, general), fiscal year and periods. |
| FR-ACC-002 | M | Taxes: percentage/fixed, included/excluded, repartition lines, tax groups, tax report. |
| FR-ACC-003 | M | Customer invoices, credit notes, vendor bills, vendor refunds, journal entries; `move_type` and `state = draft/posted/cancel`. |
| FR-ACC-004 | M | Posting validates balance (debit = credit), assigns sequence number, locks the entry and writes the audit log. |
| FR-ACC-005 | M | Payments (inbound/outbound) with journal, method, amount, currency, partner; partial payments and payment states. |
| FR-ACC-006 | M | Reconciliation of receivable/payable lines, full and partial, with write-off. |
| FR-ACC-007 | M | Payment terms (net 30, 2/10 net 30, instalments) and due dates. |
| FR-ACC-008 | M | Fiscal positions mapping taxes and accounts by country/group/zip/VAT. |
| FR-ACC-009 | M | Reports: Balance Sheet, P&L, Cash Flow, Trial Balance, General Ledger, Partner Ledger, Aged Receivable/Payable, Tax Report, Invoice Analysis. |
| FR-ACC-010 | M | Lock dates and secure entries; posted entries immutable (reversal only). |
| FR-ACC-011 | M | Multi-currency: company currency, document currency, exchange difference entries. |
| FR-ACC-012 | M | `total_invoiced`, `credit`, `debit`, `credit_to_invoice`, `days_sales_outstanding` on partners. |
| FR-ACC-013 | M | Follow-up levels and reminder emails for overdue customer invoices. |
| FR-ACC-014 | S | Analytic accounts and distribution on lines. |
| FR-ACC-015 | S | Assets and revenue recognition schedules. |
| FR-ACC-016 | S | e-invoicing / fiscal device integration (e.g. KRA eTIMS) behind a pluggable adapter. |
| FR-ACC-017 | S | Bank statement import and bank reconciliation widget. |

---

## 7. Cross-module journeys (acceptance scenarios)

### 7.1 Quote to cash

```
Contacts: customer + invoice/delivery addresses
   │
Sales: Quotation ──confirm──► Sales Order ──► create delivery (Inventory)
   │                                             │
   │                                             └── validate ──► stock.move done
   │                                                              └── valuation entry (Accounting)
   └── create invoice (Accounting) ──post──► receivable ──payment──► reconciled
```

Acceptance checks:

| Step | Expected result |
|---|---|
| Confirm quotation | State `sale`; one delivery picking in `confirmed`/`assigned`; `invoice_status = to invoice` |
| Validate delivery | Quant decreases at stock; customer location increases; `qty_delivered` updated on the sales line |
| Create invoice | Invoice in `draft` with same partner, currency, taxes, payment terms; `invoice_origin` = SO number |
| Post invoice | Journal entry balanced; receivable line created; partner `total_invoiced` increases |
| Register payment | Payment in `in_payment`/`paid`; invoice `payment_state = paid`; receivable reconciled |
| Cancel before delivery | Delivery cancelled; no accounting entry |

### 7.2 Procure to pay

```
Purchase: RFQ ──confirm──► Purchase Order ──► receipt (Inventory)
   │                                          └── validate ──► quant up, valuation entry
   └── create bill (Accounting) ──post──► payable ──payment──► reconciled
```

Acceptance checks:

| Step | Expected result |
|---|---|
| Confirm RFQ | State `purchase`; receipt created; `receipt_status = pending` |
| Receive partially | `receipt_status = partial`; `qty_received` updated |
| Receive fully | `receipt_status = full`; bill control policy respected |
| Create bill | Vendor bill with matching lines; `invoice_status = invoiced` after post |
| Pay bill | Payable reconciled; partner `debit` decreases |

### 7.3 Stock adjustment and valuation

| Action | Inventory effect | Accounting effect |
|---|---|---|
| Physical inventory count | Adjustment move to `inventory` location; quant corrected | Valuation entry (perpetual) or closing entry (periodic) |
| Scrap | Move to scrap location; quant down | Loss/expense entry |
| Internal transfer | Quant moves between internal locations | No entry |
| Delivery | Quant down; customer location up | COGS / stock-out entry (perpetual) |

### 7.4 Contact governance

- Deleting a partner referenced by any document is blocked; the UI offers **Archive**.
- Archiving a partner linked to an active user is blocked with the same rule as Odoo.
- Changing a company address propagates to `type=contact` children.
- Changing a child's VAT propagates to the company (sync rule).
- A duplicate VAT warning is shown but does not block saving.

---

## 8. Configuration and settings parity

Each app has a **Configuration → Settings** screen. Settings are stored as typed
system parameters, grouped by app and company, and are read through a cached
`settings` service.

### 8.1 Contacts settings

| Group | Setting | Default |
|---|---|---|
| Contacts | Contact Creation (who may create/edit) | Administrators only (mirrors Odoo 19) |
| Contacts | Duplicate detection on VAT / company registry | On (warning) |
| Contacts | Default country | Company country |
| Localization | Countries / states / groups available | Seeded |
| Banks | Bank directory management | Administrators |

### 8.2 Sales settings

| Group | Setting | Default |
|---|---|---|
| Quotations & Orders | Default quotation validity (days) | 30 |
| Quotations & Orders | Lock confirmed orders | Off |
| Quotations & Orders | Warning on sales orders | Off |
| Pricing | Pricelists | On |
| Pricing | Discounts | On |
| Invoicing | Invoice what is ordered / delivered | Ordered |
| Invoicing | Pro-forma invoices | Off |
| Delivery | Shipping methods | On |
| Teams | Sales teams | On |

### 8.3 Purchase settings

| Group | Setting | Default |
|---|---|---|
| Orders | Lock confirmed orders | Off |
| Orders | Warning on purchase orders | Off |
| Orders | Purchase approval threshold | Off |
| Invoicing | Bill control: ordered / received / received qty | Received |
| Products | Variants, units of measure, packagings | On |
| Vendors | Receipt reminder | Off |

### 8.4 Inventory settings

| Group | Setting | Default |
|---|---|---|
| Warehouse | Multi-step routes | Off |
| Warehouse | Storage locations | On |
| Operations | Reservation method | At confirmation |
| Operations | Packages | Off |
| Traceability | Lots & serial numbers | Off |
| Traceability | Expiration dates | Off |
| Valuation | Valuation mode (periodic / perpetual) | Periodic |
| Barcode | Barcode scanners | Off |
| Shipping | Delivery methods, package types | On |

### 8.5 Accounting settings

| Group | Setting | Default |
|---|---|---|
| Fiscal | Fiscal localization / chart template | Country default |
| Taxes | Default taxes, tax calculation rounding | Country default |
| Currencies | Multi-currency | Off |
| Journals | Default journals per operation | Seeded |
| Invoicing | Payment terms, follow-up, incoterms | Seeded |
| Fiscal positions | Automatic detection | On |
| Lock dates | Sales/purchase/hard lock | Off |
| Analytic | Analytic accounting | Off |
| Assets | Assets management | Off |
| e-Invoicing | Provider adapter | Disabled |

---

## 9. Data and reporting requirements

### 9.1 Data ownership

| Entity | Owner module | Consumers |
|---|---|---|
| Partner, tags, industries, banks, countries | `contacts` (model in `core`) | all |
| Product, variants, UoM, categories, attributes | `core` (product) | sales, purchase, inventory, accounting |
| Sale orders, lines, teams, pricelists | `sales` | accounting, inventory (read) |
| Purchase orders, lines, vendor prices, agreements | `purchase` | accounting, inventory (read) |
| Warehouses, locations, quants, pickings, moves, lots | `inventory` | sales, purchase, accounting (read) |
| Accounts, journals, taxes, moves, payments | `accounting` | all (read for smart buttons) |

### 9.2 Reporting

| Report | App | Type | Filters |
|---|---|---|---|
| Sales Analysis | Sales | Pivot/graph/list | Date, team, salesperson, product, customer |
| Purchase Analysis | Purchase | Pivot/graph/list | Date, vendor, product, category |
| Stock on Hand | Inventory | List | Location, product, lot, owner |
| Moves History | Inventory | List | Date, product, location, state |
| Stock Valuation | Inventory/Accounting | List + total | Date, product, location |
| Trial Balance | Accounting | List | Period, journal, account |
| General Ledger | Accounting | List | Account, partner, period |
| Partner Ledger | Accounting | List | Partner, period |
| Aged Receivable/Payable | Accounting | List | As-of date, partner |
| Balance Sheet / P&L | Accounting | Statement | Period, comparison |
| Tax Report | Accounting | Statement | Period, tax group |

All reports are read-only projections; none writes to operational tables.

---

## 10. Non-functional requirements

| ID | Area | Requirement |
|---|---|---|
| NFR-001 | Performance | List views paginate server-side (default 80, max 500); no query returns more than 5 000 rows to the UI. |
| NFR-002 | Performance | Document confirm/post under 1.5 s p95 for 50-line documents. |
| NFR-003 | Concurrency | Two users editing the same document: last write wins only for non-state fields; state transitions use optimistic locking (`version`). |
| NFR-004 | Consistency | All cross-module operations run in one transaction or via the outbox; no partial documents. |
| NFR-005 | Security | Passwords hashed (Argon2id), sessions HttpOnly/Secure/SameSite, CSRF on all mutating routes. |
| NFR-006 | Security | ACL + record rules enforced server-side on every read/write, including exports and reports. |
| NFR-007 | Audit | Immutable audit log for state changes, postings, deletions, permission changes, settings changes. |
| NFR-008 | Reliability | Daily full backup + WAL archiving; RPO ≤ 15 min, RTO ≤ 4 h. |
| NFR-009 | Availability | 99.5 % monthly for the app; maintenance windows announced. |
| NFR-010 | i18n | English + one additional locale at launch; all strings translatable; dates/numbers per user locale. |
| NFR-011 | Timezone | Store UTC; display in user timezone; accounting dates are dates (no timezone conversion). |
| NFR-012 | Accessibility | WCAG 2.2 AA on launcher, forms, lists, dialogs. |
| NFR-013 | Browser support | Last 2 versions of Chrome, Edge, Firefox, Safari; 1280×720 minimum. |
| NFR-014 | Observability | Structured logs, request IDs, metrics (latency, errors, queue depth), health endpoints. |
| NFR-015 | Portability | Docker Compose deployment; no cloud-specific services required. |
| NFR-016 | Data retention | Documents retained 10 years; audit log immutable; attachments versioned. |

---

## 11. Acceptance and definition of done

A requirement is done only when:

1. The menu/action exists at the specified path and survives reload.
2. The list, form, search and (where relevant) kanban views exist with the specified fields.
3. Server-side validation and permissions are enforced (not only UI).
4. Unit + integration tests cover the happy path and the stated failure modes.
5. The cross-module contract is covered by a contract test.
6. Audit events are emitted.
7. Documentation and screenshots are updated.
8. Product owner signs the demo script in `phases.md`.

### 11.1 UAT script (summary)

| # | Script | Pass condition |
|---|---|---|
| UAT-01 | Launch product → five icons → open each app | Each app opens its home action; menubar matches §5.2 |
| UAT-02 | Create company + 2 addresses + tag + bank | Saved; `complete_name` correct; address sync correct |
| UAT-03 | Quote → confirm → deliver → invoice → pay | All documents linked; ledger balanced |
| UAT-04 | RFQ → approve → receive → bill → pay | Receipt status and bill control correct |
| UAT-05 | Count stock, scrap, transfer | Quants correct; valuation entries correct |
| UAT-06 | Post invoice, reconcile partial payment | `payment_state = partial`; balances correct |
| UAT-07 | Attempt to delete a used partner | Blocked with readable message; archive works |
| UAT-08 | Restricted user opens Accounting | Menus hidden; direct URL returns 403 |
| UAT-09 | Reports | Totals reconcile with ledger/stock |

---

## 12. Release scope

| Release | Content | Phases (`phases.md`) |
|---|---|---|
| R0 | Platform, launcher, auth, shared kernel | P0 |
| R1 | Contacts + Sales core + Inventory core + Accounting core | C1, S1, I1, A1 |
| R2 | Purchase + cross-app flows + invoicing | P1, P2, S2, I2, A2 |
| R3 | Agreements, reporting, valuation, reconciliation, full menu parity | P3, C2, S3, I3, A3 |
| GA | Parity audit, hardening, migration, UAT, go-live | F1 |

Each module has at least two delivery phases; see [`phases.md`](phases.md).

---

## 13. Out of scope (explicit)

- Odoo source code, Odoo database schema, Odoo XML IDs and Odoo branding.
- Odoo Studio, website, eCommerce, manufacturing, HR/payroll, projects.
- Multi-tenant SaaS, per-tenant databases, subscription billing.
- Native mobile apps.
- Marketplace / third-party app installation.

---

## 14. Glossary

| Term | Meaning |
|---|---|
| **App** | One of the five launcher icons. |
| **Module** | A deployable unit with a manifest, models, views, data and tests. |
| **Action** | A window action that opens a model with views (list/form/kanban). |
| **Menu** | A record pointing to an action or to child menus. |
| **Partner** | Company, person or address in the shared directory. |
| **Commercial entity** | The company (or root person) that owns a business relationship. |
| **Picking** | Inventory transfer document (receipt, delivery, internal). |
| **Quant** | On-hand quantity per product/location/lot. |
| **Move** | Accounting journal item; also used for stock movement (`stock.move`). |
| **Posting** | Making a journal entry final and immutable. |
| **Outbox** | Table of domain events written in the same transaction as the change. |
| **Smart button** | Statistic button on a form linking to related documents. |
| **Chatter** | Message/activity panel on a record. |
| **Parity** | Functional and navigational equivalence with the Odoo reference. |

---

*End of PRD. Continue with [`architecture.md`](architecture.md).*
