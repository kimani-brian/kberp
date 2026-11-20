# KB ERP — Design Specification

| Field | Value |
|---|---|
| Product | **KB ERP** (`kberp`) |
| Version | 1.0 |
| Scope | Launcher + **Contacts, Sales, Purchase, Inventory, Accounting** |
| Audience | Product design, frontend engineering, QA |
| Companion documents | [`prd.md`](prd.md) · [`architecture.md`](architecture.md) · [`rules.md`](rules.md) · [`phases.md`](phases.md) |

---

## 1. Design principles

| # | Principle | What it means in the UI |
|---|---|---|
| D1 | **One door, five rooms** | The launcher is the front door; every app is a room with its own menubar, but all rooms share the same furniture |
| D2 | **Density with air** | ERP screens are data-dense; spacing, alignment and typography do the work instead of decoration |
| D3 | **The document is the hero** | Forms lead with the document identity, status and totals; configuration is secondary |
| D4 | **Show, don't hide** | Smart buttons and status bars surface related work instead of forcing navigation |
| D5 | **Same pattern everywhere** | List, form, search and chatter behave identically in all five apps |
| D6 | **Fast feedback** | Every action acknowledges within 100 ms; long actions show progress and can continue in the background |
| D7 | **Reversible by design** | Destructive actions are confirmed; documents are cancelled/archived, not deleted |
| D8 | **Accessible by default** | Keyboard-first, visible focus, AA contrast, no colour-only meaning |

---

## 2. Design tokens

### 2.1 Colour

The shell is sky blue and cloud white: a cool, bright canvas with a deep sky
for actions. App accents stay distinct so the launcher reads at a glance.

| Token | Value | Usage |
|---|---|---|
| `--kb-bg` | `#F4FAFE` | Page background (cloud white) |
| `--kb-surface` | `#FFFFFF` | Cards, sheets |
| `--kb-surface-alt` | `#EAF4FB` | Table header, zebra |
| `--kb-surface-hover` | `#F2F9FD` | Row hover |
| `--kb-border` | `#D3E4F0` | Dividers, inputs |
| `--kb-text` | `#12212E` | Primary text |
| `--kb-text-muted` | `#526B7E` | Secondary text |
| `--kb-primary` | `#0369A1` | Primary actions, links |
| `--kb-primary-hover` | `#075985` | Hover/active |
| `--kb-primary-soft` | `#E0F2FE` | Selected chips, tag tints |
| `--kb-focus` | `#0284C7` | Focus ring |
| `--kb-success` | `#15803D` | Posted, done, paid |
| `--kb-warning` | `#B45309` | To invoice, partial, warnings |
| `--kb-danger` | `#B91C1C` | Errors, overdue, negative |
| `--kb-info` | `#0369A1` | Informational |
| `--kb-accent-contacts` | `#0284C7` | Contacts app |
| `--kb-accent-sales` | `#4F46E5` | Sales app |
| `--kb-accent-accounting` | `#0F766E` | Accounting app |
| `--kb-accent-purchase` | `#B45309` | Purchase app |
| `--kb-accent-inventory` | `#1D4ED8` | Inventory app |

Contrast: all text/background pairs meet WCAG AA (4.5:1 body, 3:1 large). The
page carries one soft sky wash at the top; content surfaces stay cloud white so
tables and forms keep their calm. Translucent chrome uses
`backdrop-filter: blur(20px) saturate(180%)` and falls back to an opaque surface
under `prefers-reduced-transparency`.

### 2.2 Typography

| Token | Size / line | Weight | Usage |
|---|---|---|---|
| `--kb-font` | `"Inter", system-ui, sans-serif` | 400 | Body |
| `--kb-text-xs` | 12 / 16 | 500 | Table meta, badges |
| `--kb-text-sm` | 13 / 18 | 400 | Tables, forms |
| `--kb-text-md` | 14 / 20 | 400 | Default body |
| `--kb-text-lg` | 16 / 24 | 500 | Section titles |
| `--kb-text-xl` | 20 / 28 | 600 | Page titles |
| `--kb-display` | 28 / 36 | 650 | Launcher, dashboard KPIs |
| `--kb-mono` | `"JetBrains Mono", monospace` | 400 | Numbers, codes, references |

Numbers use tabular figures in tables and totals.

### 2.3 Spacing, radius, elevation, motion

| Token | Value |
|---|---|
| `--kb-space-1 … 8` | 4, 8, 12, 16, 24, 32, 48, 64 px |
| `--kb-radius-sm` | 4 px |
| `--kb-radius-md` | 8 px |
| `--kb-radius-lg` | 12 px |
| `--kb-shadow-1` | `0 1px 2px rgba(16,24,40,.06)` |
| `--kb-shadow-2` | `0 4px 12px rgba(16,24,40,.10)` |
| `--kb-shadow-3` | `0 12px 32px rgba(16,24,40,.16)` |
| `--kb-duration-fast` | 120 ms |
| `--kb-duration-base` | 200 ms |
| `--kb-ease` | `cubic-bezier(.2,.8,.2,1)` |

Motion is used for overlays, drawers and launcher transitions only; no decorative
animation on data screens. `prefers-reduced-motion` disables transforms.

### 2.4 Iconography

- 20 px stroke icons in the UI (`lucide`-style), 1.75 px stroke.
- 48 px app icons in the launcher, custom per app, duotone using the app accent.
- Status icons: check (done), clock (waiting), alert (warning), ban (cancelled).
- Never use colour alone: pair with icon or text.

---

## 3. The launcher

### 3.1 Purpose

The launcher is the first screen after login. It answers: *what can I do here?*
It shows the five applications, a search field, recent documents and favourites.

### 3.2 Layout (desktop ≥ 1024 px)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  KB ERP                                    [Search]        [Bell]  [Avatar]  │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Good morning, Brian                                                        │
│   What would you like to work on?                                            │
│                                                                              │
│   ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────┐ │
│   │   [icon]   │  │   [icon]   │  │   [icon]   │  │   [icon]   │  │ [icon] │ │
│   │  Contacts  │  │   Sales    │  │ Accounting │  │  Purchase  │  │Inventory│ │
│   │ Directory  │  │ Quote→cash │  │ Ledger     │  │ Procure    │  │ Stock  │ │
│   └────────────┘  └────────────┘  └────────────┘  └────────────┘  └────────┘ │
│                                                                              │
│   Recent                                                                     │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │ SO/2026/00142 · Apex Logistics · KES 148,200 · Quotation  2 min ago  │   │
│   │ INV/2026/00087 · SafeGuard Insurance · Posted             1 h ago    │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   Favourites  ★ Quotations  ★ Stock on Hand  ★ Aged Receivable               │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 App card specification

| Property | Value |
|---|---|
| Size | 176 × 152 px (desktop), 156 × 140 (tablet) |
| Radius | 12 px |
| Surface | White, 1 px border, shadow 1 |
| Hover | Border → app accent, shadow 2, translateY(-2 px) |
| Focus | 2 px focus ring, 2 px offset |
| Icon | 48 px, centred, app accent duotone |
| Title | 16 px / 600 |
| Description | 13 px / muted, one line, ellipsis |
| Badge | Optional count (e.g. "12 to invoice") top-right |
| Click target | Entire card |
| Keyboard | `Tab` order = visual order; `Enter` opens |

Default order follows app `sequence`: Contacts, Sales, Accounting, Purchase,
Inventory. Hovering a card does **not** auto-open; click/Enter only.

### 3.4 App switcher overlay

- Triggered by the 3×3 grid icon or `Alt+W` from any app.
- Opens as a centred overlay (max 900 px) with the same five cards in a 5-column row.
- `Esc` closes; focus returns to the trigger.
- Includes a **Settings** entry for administrators (gear, secondary style).
- Shows the current app with a check mark.

### 3.5 Launcher states

| State | Behaviour |
|---|---|
| Loading | Five skeleton cards, no spinner |
| Empty recents | Section hidden, not an empty box |
| Search with no result | "No app matches 'x'" + clear action |
| Restricted app | Card hidden if the user has no access to any of its menus |
| First login | Welcome line + a 3-step checklist (create a contact, create a product, send a quotation) |

### 3.6 Responsive

| Breakpoint | Grid |
|---|---|
| ≥ 1280 | 5 columns |
| 1024–1279 | 5 columns, narrower cards |
| 768–1023 | 3 columns |
| < 768 | 2 columns, cards 1:1, description hidden |

---

## 4. App shell

### 4.1 Structure

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ [▦]  Sales   Orders  To Invoice  Products  Reporting  Configuration   🔍  🔔  │
├──────────────────────────────────────────────────────────────────────────────┤
│ Sales / Orders / Quotations                                      [ New ]     │
├──────────────────────────────────────────────────────────────────────────────┤
│  Search…            Filters  Group By  ⚙ Columns           1–80 of 342       │
├──────────────────────────────────────────────────────────────────────────────┤
│  ☐  Number        Customer           Date        Total      Status           │
│  ☐  SO/2026/0142  Apex Logistics     14 Nov     148,200    Quotation        │
│  ☐  SO/2026/0141  SafeGuard Ins.     14 Nov      92,400    Sales Order      │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Top bar

| Region | Content | Behaviour |
|---|---|---|
| Left | App switcher, app name | Switcher opens overlay; app name links to app home |
| Centre | Menubar (max 6 top-level items) | Click opens dropdown; hover after 150 ms opens |
| Right | Global search, activity bell, user menu | Search `Alt+Q`; bell shows activities/messages; avatar shows profile, preferences, logout |

Menubar overflow: items beyond 6 collapse into a "More" menu; the order is the menu
`sequence`.

### 4.3 Submenu / dropdown

- Max width 280 px; items 36 px tall.
- Section separators for groups of related actions.
- A submenu with children opens a flyout to the right.
- Active item has a left accent bar and accent text.
- Keyboard: `↑/↓` moves, `→` opens flyout, `←` closes, `Enter` activates, `Esc` closes.

### 4.4 Breadcrumbs

`App / Section / Subsection / Record`. The last segment is the record display name
(truncated at 40 chars). Clicking a segment navigates to that action.

### 4.5 Status bar (documents)

```
Quotation ─── Quotation Sent ─── Sales Order ─── Cancelled
    ●
```

- Completed steps: filled accent dot + medium text.
- Current state: larger dot, bold text, accent.
- Future steps: hollow dot, muted text.
- Cancelled is terminal and shown in danger colour, never as a step in the flow.
- Arrow buttons (`← →`) in the top-right move between records in the current list.

### 4.6 Smart buttons

- Row under the document title, right-aligned when space allows.
- Each: icon, value (tabular), label (11 px uppercase muted).
- Hidden when the count is zero, except "Invoiced" which shows the monetary total.
- Click navigates to the related list, filtered by the current record.

### 4.7 Chatter

- Right column on wide screens (≥ 1440), below the form on narrower screens.
- Tabs: **Send message** / **Log note** / **Activities**.
- Composer with @mentions, emoji, attachment, and "Schedule activity".
- Message cards: avatar, author, timestamp, body, attachments, tracking changes.
- Activities: coloured icon by type, summary, due date, "Mark done" and "Reschedule".

---

## 5. Navigation model

| Rule | Detail |
|---|---|
| URL is truth | `/apps/<app>/<action-path>[/<record-id>]` |
| Reload | Same view, same filters, same page |
| Back/forward | Traverses view and record history |
| App home | Clicking the app name goes to the app's default action |
| New tab | `Ctrl/Cmd+click` on a menu opens a new tab at the same action |
| Deep link to record | Opens the record form with breadcrumbs |
| Unknown path | 404 page with "Back to apps" and search |
| Forbidden | 403 page with the missing permission explained |

---

## 6. View patterns

### 6.1 List view

| Element | Spec |
|---|---|
| Header | Sticky; sortable columns with ▲/▼; numeric columns right-aligned |
| Rows | 40 px; hover `--kb-surface-alt`; selected row accent tint |
| Selection | Checkbox column; header checkbox selects page |
| Inline edit | Only where explicitly enabled (e.g. quantity in a picking) |
| Columns | Optional show/hide via "⚙ Columns", persisted per user/model |
| Totals | Footer row for numeric columns (sum) |
| Pagination | 1–80 of N, page size 80/200/500 |
| Empty | Illustration + explanation + primary action |
| Bulk actions | Action menu (Export, Archive, Print, custom) |
| Row actions | Open (click), duplicate, delete (draft only) |

### 6.2 Kanban view

- Cards in responsive columns; column width 272 px.
- Card: image/avatar or icon, title, 2–3 meta lines, tags, footer statistics.
- Group by a field (state, salesperson, team, warehouse); drag between groups only
  where the business allows it (never between accounting states).
- Quick create at the bottom of a column.
- Used for: contacts (addresses), quotations, pickings, products.

### 6.3 Form view

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ‹ ›   SO/2026/0142                              [Send] [Confirm] [⋯]         │
│       Apex Logistics Ltd                                                     │
│       ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                     │
│       │ KES 148,200  │ │ 3 deliveries │ │ 2 invoices   │                     │
│       │ Total        │ │ Deliveries   │ │ Invoices     │                     │
│       └──────────────┘ └──────────────┘ └──────────────┘                     │
│  ── Quotation ──●── Quotation Sent ── Sales Order ── Cancelled               │
│                                                                              │
│  Customer        Apex Logistics Ltd        │  Order Date     14 Nov 2026     │
│  Invoice Address Apex Logistics Ltd        │  Expiration     14 Dec 2026     │
│  Delivery Address Warehouse, Nairobi       │  Pricelist      KES Retail      │
│  Payment Terms   Net 30                    │  Salesperson    Brian K.        │
│                                                                              │
│  [Order Lines] [Other Info] [Notes]                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ Product        Description      Qty  UoM  Unit Price  Disc  Taxes Total│  │
│  │ [FURN_001]     Desk 120cm        10  Units   12,000    5%   16%  114,000│ │
│  │ + Add a line                                                           │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│                                                Untaxed  132,000              │
│                                                Taxes     21,120              │
│                                                Total    153,120              │
└──────────────────────────────────────────────────────────────────────────────┘
```

Rules:

- Two-column layout for header fields; address blocks use the country format.
- Title = document number (or partner name for contacts); subtitle = main party.
- Status bar under the title, smart buttons right.
- Tabs: business sections, `Notes` last.
- Sticky footer with totals and primary action on long forms.
- Required fields marked with `*`; validation on blur and on submit.
- Unsaved changes prompt before navigation.

### 6.4 Search, filters, group-by

| Element | Spec |
|---|---|
| Search input | Free text; searches the model's `_rec_names_search` fields |
| Filter chips | Removable; each shows field + operator + value |
| Quick filters | "My records", "This month", "Draft", "To invoice" |
| Group by | One or more fields; chips with remove |
| Favourites | Save current search with a name; shared or private |
| Default | Each action declares its default filters |
| Date range | Presets (today, this week, month, quarter, year, custom) |

### 6.5 Pivot and graph

- Pivot: rows, columns, measures; expandable; export to XLSX.
- Graph: bar (default), line, pie; must have a measure and a group-by.
- No graph without numbers; empty state suggests a measure.

### 6.6 Activity view

- Grouped by activity type; overdue first.
- Each row: record, summary, due date, responsible, "Mark done".
- Used by Sales and Contacts.

---

## 7. Per-module screens

### 7.1 Contacts

**List** — Name (complete name), Email, Phone, Salesperson, City, Country, Tags,
statistics badge. Filters: Persons, Companies, Archived. Group by: Salesperson,
Company, Country, Tags.

**Kanban** — Avatar (with parent company badge for individuals), name, email, phone,
city/country, tags, footer statistics.

**Form** — header: photo, Person/Company radio, name, email, phone; left: company
link, address block; right: job position, VAT, website, language, tags; properties;
tabs:

| Tab | Content |
|---|---|
| **Contacts** | Kanban of addresses/contacts; address type; address block when not `contact`; internal notes |
| **Sales & Purchase** | Salesperson, payment terms/method, buyer, supplier currency, receipt reminder, warnings, company registry, reference, company, industry, fiscal position |
| **Invoicing** | Bank accounts, receivable/payable accounts, invoice sending/EDI, credit limit, DSO, abnormal-invoice flags (hidden for child contacts; link to parent instead) |
| **Notes** | Internal notes and warning fields |

Smart buttons: Invoiced, Vendor Bills, Sales, Purchases, Lots/Serials, Saved Payment
Methods.

**Configuration screens** — tags (hierarchical list + colour), industries, countries,
states, country groups, banks, bank accounts. Each is a simple list/form with the
standard search and chatter where relevant.

### 7.2 Sales

| Screen | Key elements |
|---|---|
| Quotations list | Number, customer, date, expiration, salesperson, team, total, status; filters Draft/Sent/My quotations; "New" opens the quotation form |
| Quotation form | Customer + addresses, pricelist, payment terms, validity, salesperson/team, tags; lines with product picker, description, qty, UoM, price, discount, taxes, subtotal; totals panel; "Send", "Confirm", "Create Invoice", "Preview" |
| Sales Orders list | Same columns, confirmed filter, lock indicator |
| To Invoice | Orders with invoice status `to invoice`, grouped by customer |
| Upsell | Orders with invoice status `upselling`, showing ordered vs invoiced qty |
| Products | Product cards/list with sales price, on hand, forecast, sales count |
| Pricelists | List + form with rules (product/category, min qty, fixed/percentage/formula, dates, currency) |
| Sales Teams | Kanban by team with members, targets and this-month invoiced |
| Reporting | Sales analysis pivot (date × team/salesperson/product), graph, list |
| Configuration | Settings; teams; quotation templates; headers/footers; delivery methods; tags; attributes; combo choices; categories; product tags; units & packagings; online payments; activities |

**Quotation form interaction notes**

- Customer selection fills invoice address, delivery address, pricelist, payment
  terms and salesperson.
- Adding a product opens a searchable picker showing price, on-hand and UoM.
- Changing qty recomputes discount/tax/total inline without a page reload.
- "Send" opens an email composer with the quotation PDF attached.
- "Confirm" asks for confirmation if a warning applies; success shows the delivery
  smart button.
- "Create Invoice" opens a wizard when a down payment is configured, otherwise opens
  the draft invoice.

### 7.3 Purchase

| Screen | Key elements |
|---|---|
| RFQ list | Number, vendor, buyer, date, expected arrival, total, status; "New" |
| RFQ form | Vendor, currency, payment terms, buyer, expected arrival, incoterm, lines (product, qty, price, taxes, subtotal), totals; "Send", "Confirm", "Print" |
| Purchase Orders | Confirmed filter, receipt status chip, lock indicator, "Create Bill", "Receive" |
| Agreements | List + form with vendor, validity, lines, ordered vs called-off quantity |
| Vendors | Partner list filtered to suppliers with purchase statistics |
| Reporting | Purchase analysis by vendor/product/category/date |
| Configuration | Settings; vendor pricelists; attributes; categories; units & packagings |

**Receipt status chips** — Not Received (grey), Partially Received (amber), Fully
Received (green). **Bill control** — when the policy is "received", "Create Bill"
is disabled until a receipt is validated, with an inline explanation.

### 7.4 Inventory

| Screen | Key elements |
|---|---|
| Overview | KPI cards (to receive, to deliver, late transfers, stock value), warehouse filter, quick actions |
| Transfers | Tabs Receipts / Deliveries / Internal; list with number, partner, scheduled date, source→destination, status, late badge |
| Transfer form | Operation type, partner, scheduled date, source/destination, moves (product, demand, done, UoM), detailed operations (lot, package, owner), "Check availability", "Validate", backorder dialog |
| Adjustments | Physical inventory count sheet (product, location, counted, difference), Scrap form |
| Replenishment | Orderpoints with min/max, to-order, forecast; "Order" creates an RFQ |
| Products | Product list with on-hand, forecast, free-to-use; product form Inventory tab |
| Lots / Serials | List + form with product, lot name, quantities, traceability links |
| Packages | Package list + contents |
| Reporting | Stock, Locations, Moves History, Moves Analysis, Performance |
| Configuration | Settings; warehouses; operation types; locations (tree); routes; rules; storage categories; putaway rules; categories; attributes; units & packagings; barcode nomenclatures; delivery methods; package types; zip prefix |

**Validation dialog** — shows demand vs done, backorder option (create/no backorder),
and a warning if quantities differ. Errors (missing lot, negative stock) are shown
per line.

### 7.5 Accounting

| Screen | Key elements |
|---|---|
| Dashboard | KPI cards (revenue, expenses, profit, cash), bank balances, invoice/bill pipeline, aged receivables, charts |
| Invoices | List: number, customer, invoice date, due date, total, status, payment status; filters Draft/Posted/Overdue/My; "New Invoice" |
| Invoice form | Customer, invoice date, due date, payment terms, journal, currency; lines (product, label, qty, price, taxes, subtotal); totals; "Post", "Send", "Register Payment", "Preview", "Credit Note" |
| Credit notes | Same form with `out_refund`; link to original invoice |
| Payments | List: number, date, partner, journal, amount, status; payment form with allocation table |
| Bills | Vendor, bill date, due date, reference, lines, "Post", "Register Payment" |
| Journal entries | List: number, date, journal, reference, partner, debit, credit, status; entry form with balanced lines and a balance indicator |
| Reconcile | Split view: statement lines left, open receivable/payable right; match, partial, write-off |
| Reports | Statement (Balance Sheet, P&L, Cash Flow), Ledgers (Trial Balance, General Ledger), Partner reports (Partner Ledger, Aged Receivable/Payable), Taxes, Management |
| Configuration | Settings; chart of accounts; taxes; journals; payment terms; fiscal positions; follow-up levels; incoterms; product categories; assets; analytic; online payments |

**Invoice form specifics**

- Status bar: Draft → Posted → (Paid chip).
- Payment status chip: Not Paid (grey), Partial (amber), Paid (green), Reversed (red).
- Totals block: untaxed, tax groups, total, amount due.
- "Register Payment" opens a dialog with journal, amount (default residual), date,
  method, memo; validates overpayment.
- Posted invoices are read-only; "Reset to Draft" is not offered; "Credit Note" and
  "Reverse" are.

**Statements** — two-column layout: left account hierarchy with drill-down, right
amounts for current and comparison period; expand/collapse; export to PDF/XLSX.

---

## 8. Component inventory

| Component | Used by | Notes |
|---|---|---|
| `AppLauncher` | shell | Five cards, search, recents |
| `AppSwitcher` | shell | Overlay, keyboard |
| `MenuBar` / `MenuDropdown` | shell | Server-driven tree |
| `Breadcrumbs` | shell | Record-aware |
| `SearchBar` + `FilterChips` | all lists | Saved favourites |
| `DataTable` | all lists | Sticky header, sort, selection, totals |
| `KanbanBoard` | contacts, sales, teams, pickings | Grouped columns |
| `FormSheet` | all forms | Two-column, tabs, sticky footer |
| `StatusBar` | documents | State machine |
| `SmartButton` / `SmartButtonRow` | documents | Statistic links |
| `Many2OnePicker` | all forms | Search, create, open |
| `ProductPicker` | sale/purchase/invoice lines | Price, on-hand, UoM |
| `LineEditor` | sale/purchase/invoice/transfer | Editable grid with keyboard |
| `TotalsPanel` | sale/purchase/invoice | Untaxed, taxes, total |
| `Chatter` | documents, contacts | Messages, notes, activities |
| `ActivityBell` | shell | Unread count, dropdown |
| `NotificationToast` | shell | Success/error/warning, action link |
| `ConfirmDialog` | all | Destructive/irreversible actions |
| `WizardDialog` | all | Multi-step, progress |
| `ImportDialog` | lists | Upload, mapping, validation, errors |
| `ReportViewer` | reports | PDF preview, download, print |
| `EmptyState` | all | Icon, explanation, primary action |
| `PermissionNotice` | all | 403 explanation |

---

## 9. Feedback and error patterns

| Situation | Pattern |
|---|---|
| Save success | Toast 3 s, "Saved" + optional "Undo" for reversible actions |
| Validation error | Inline message under the field + summary toast; focus first invalid field |
| Business rule violation | Dialog with rule explanation and the corrective action |
| Warning (e.g. customer warning) | Amber dialog with "Continue" and "Cancel"; continue is explicit |
| Long operation | Button becomes progress state; job continues in background; notification on completion |
| Network error | Inline banner "Reconnecting…"; retry automatically; disable writes |
| Conflict (record changed) | Dialog: reload / overwrite (overwrite only for non-state fields) |
| Permission denied | 403 page or inline notice naming the missing group |
| Delete blocked | Explain references, offer Archive |

Copy rules: say what happened, why, and what to do next. No codes alone. Examples:

- "This contact is used by 3 invoices. Archive it instead of deleting."
- "The receipt is not validated yet. Validate it before creating the bill."
- "The entry is not balanced: debit 1,200.00, credit 1,150.00."

---

## 10. Accessibility

| Requirement | Implementation |
|---|---|
| Keyboard | All actions reachable; logical tab order; `Esc` closes overlays |
| Focus | Visible 2 px ring; focus trapped in dialogs; restored on close |
| Screen readers | Semantic landmarks, labels, `aria-live` for toasts, table headers |
| Contrast | AA minimum; status colours paired with text/icons |
| Forms | Labels always visible (no placeholder-only); errors linked with `aria-describedby` |
| Tables | `scope` on headers; sortable headers announce sort state |
| Motion | Respect `prefers-reduced-motion` |
| Zoom | Usable at 200 %; no horizontal scroll at 1280 px |
| Language | `lang` attribute; translated labels |
| Time | Relative times have absolute tooltips |

---

## 11. Responsive behaviour

| Breakpoint | Shell | Forms | Lists |
|---|---|---|---|
| ≥ 1440 | Menubar + chatter side panel | Two columns | All optional columns |
| 1024–1439 | Menubar | Two columns | Core columns + column chooser |
| 768–1023 | Menubar collapses to "More" | One column, tabs horizontal scroll | Core columns |
| < 768 | Hamburger + app switch | One column, sticky actions | Card list (kanban-like) |

Minimum supported viewport: 360 × 640. No feature is desktop-only except bulk
editing of more than 50 rows.

---

## 12. Content and microcopy

| Context | Guidance | Example |
|---|---|---|
| Buttons | Verb + object, sentence case | "Create invoice", "Validate receipt" |
| Menu | Nouns, Title Case, Odoo parity | "Requests for Quotation", "To Invoice" |
| Empty state | What + why + action | "No quotations yet. Create your first quotation to start selling." |
| Errors | What + why + fix | "The delivery cannot be validated: lot number is required for tracked products." |
| Confirmations | Consequence first | "Cancelling this order will cancel its delivery. Continue?" |
| Numbers | Locale grouping, currency symbol | "KES 148,200.00" |
| Dates | `14 Nov 2026`, relative in lists | "14 Nov 2026 (2 days ago)" |
| Status | Odoo labels | "Quotation Sent", "To Approve", "Partially Received" |

---

## 13. Design QA checklist

- [ ] Launcher shows exactly five apps, in sequence order, with keyboard access.
- [ ] App switcher works from every screen and remembers the current app.
- [ ] Menubar and submenus match the parity baseline; no dead entries.
- [ ] Deep link survives reload and back/forward.
- [ ] List: search, filters, group-by, columns, pagination, export.
- [ ] Form: required fields, validation, tabs, smart buttons, status bar, chatter.
- [ ] Document totals reconcile with line values and taxes.
- [ ] Status labels match the reference.
- [ ] Empty, loading, error and forbidden states are designed.
- [ ] Contrast and focus pass automated checks.
- [ ] Mobile layout usable at 360 px.
- [ ] All strings translatable.
- [ ] Screenshots updated for changed screens.

---

*End of design. Continue with [`phases.md`](phases.md).*
