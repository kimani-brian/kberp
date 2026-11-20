# Odoo 19 — The Contacts Module

**`contacts` as an application, `res.partner` as the real model**

> Companion document to [`odoo-modules-architecture.md`](odoo-modules-architecture.md).
> Snapshot taken from the running installation at <http://localhost:8091/>.
> Odoo server version: **19.0-20260619**. Database inspected: **newdb**.
> Company: **My Company**, currency **KES**.

**Contents**

0. [How this document was produced](#0-how-this-document-was-produced)
1. [What the module actually is](#1-what-the-module-actually-is)
2. [Manifest and file map](#2-manifest-and-file-map)
3. [Dependency graph](#3-dependency-graph)
4. [Model architecture](#4-model-architecture)
5. [The company / person hierarchy](#5-the-company--person-hierarchy)
6. [Field reference](#6-field-reference)
7. [Methods and behaviours](#7-methods-and-behaviours)
8. [Chatter, activities and blacklist](#8-chatter-activities-and-blacklist)
9. [Cross-module extensions](#9-cross-module-extensions)
10. [Interconnections](#10-interconnections)
11. [UI navigation](#11-ui-navigation)
12. [Security model](#12-security-model)
13. [Data quality: duplicates, merge, archive, import](#13-data-quality-duplicates-merge-archive-import)
14. [This installation's data snapshot](#14-this-installations-data-snapshot)
15. [Extension points](#15-extension-points)
16. [Verification queries](#16-verification-queries)
17. [Pitfalls and the mental model](#17-pitfalls-and-the-mental-model)

---

## 0. How this document was produced

| Item | Value |
|---|---|
| Odoo container | `kbmart_odoo_platform` |
| PostgreSQL container | `kbmart_postgres_database` |
| UI URL | <http://localhost:8091/> |
| Database | `newdb` |
| Core addon root | `/usr/lib/python3/dist-packages/odoo/addons/` |
| Host copy used for reading | `/tmp/opencode/contacts-src/` (temporary analysis copy) |
| Installed version | `contacts 19.0.1.0` |

Everything below comes from reading the actual source in the container, plus SQL
queries against the live database for the menu tree, access rights and record counts.
File references are relative to a module root, e.g. `base/models/res_partner.py:854`.

The contacts module itself is **tiny** — two Python files of a few lines each and one
XML file of menus. The behaviour that users call "Contacts" is 95 % implemented in
`base` (`res.partner`), `mail` (chatter/activities) and the installed business modules
that add fields to `res.partner` (`account`, `sale`, `purchase`, `stock`, …).

This is the single most important thing to understand before reading further:

```
contacts/        →  application menu + activity icon  (≈100 lines total)
base/            →  res.partner, res.partner.category, res.partner.industry,
                    res.bank, res.partner.bank, res.country, res.country.state,
                    res.country.group
mail/            →  mail.activity.mixin + mail.thread.blacklist on res.partner
account/sale/    →  commercial fields added onto res.partner
purchase/stock/
```

---

## 1. What the module actually is

The `contacts` addon (`__manifest__.py`) declares:

| Key | Value |
|---|---|
| `name` | Contacts |
| `category` | Sales/CRM |
| `sequence` | 150 |
| `summary` | Centralize your address book |
| `depends` | `base`, `mail` |
| `data` | `views/contact_views.xml` |
| `demo` | `data/mail_demo.xml` |
| `application` | `True` |
| `license` | LGPL-3 |

It contributes exactly three behaviours:

1. **A root app menu** `Contacts` containing the address-book item and a
   Configuration submenu (tags, industries, localization, banks).
2. **One window action** (`contacts.action_contacts`) over `res.partner`, with list,
   kanban and form views and the `default_is_company: True` context.
3. **Two small model overrides**:
   - `contacts/models/res_partner.py:9` registers the Contacts root menu as the
     "home" menu of `res.partner` (used by mail's *Open in …* link from chatter).
   - `contacts/models/res_users.py:9` swaps the activity-systray icon for
     `res.partner` activities to the Contacts app icon.

```python
# contacts/models/res_partner.py
class ResPartner(models.Model):
    _inherit = "res.partner"

    def _get_backend_root_menu_ids(self):
        return super()._get_backend_root_menu_ids() + [self.env.ref('contacts.menu_contacts').id]
```

```python
# contacts/models/res_users.py
class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _get_activity_groups(self):
        activities = super()._get_activity_groups()
        for activity in activities:
            if activity['model'] != 'res.partner':
                continue
            activity['icon'] = modules.module.Manifest.for_addon('contacts').icon
        return activities
```

`_get_backend_root_menu_ids()` is defined as returning `[]` in
`mail/models/models.py:862` and is consumed by `mail/models/ir_ui_menu.py:40`, which
picks the highest-priority visible root menu for a model. In other words: **this is
what makes the chatter's "Open in Contacts" button land on the Contacts app rather
than on some other app that also shows partners.**

The demo file `contacts/data/mail_demo.xml` only adds a demo chatter message and a
scheduled notification on `base.res_partner_2`; it contains no partners.

---

## 2. Manifest and file map

```
contacts/
├── __init__.py
├── __manifest__.py
├── data/
│   └── mail_demo.xml            # 4 records: 1 mail.message + 1 schedule (+ refs)
├── models/
│   ├── __init__.py
│   ├── res_partner.py           # 11 lines
│   └── res_users.py             # 18 lines
├── views/
│   └── contact_views.xml        # 96 lines: 1 action, 1 action-view set, 11 menus
└── tests/
    └── test_ui.py               # UI tour: "Set Defaults" on company_type
```

`contact_views.xml` in full is reproduced structurally below (line numbers from the
container copy):

| Line | Record | Purpose |
|---|---|---|
| 3 | `action_contacts` | Window action over `res.partner`, `list,kanban,form,activity`, `path=contacts`, `context={'default_is_company': True}` |
| 18 | `action_contacts_view_kanban` | sequence 1 → `base.res_partner_kanban_view` |
| 24 | `action_contacts_view_tree` | sequence 0 → `base.view_partner_tree` |
| 30 | `action_contacts_view_form` | sequence 2 → `base.view_partner_form` |
| 38 | `menu_contacts` | root menu, sequence 20, groups `base.group_user,base.group_partner_manager` |
| 44 | `res_partner_menu_contacts` | "Contacts" item, sequence 2 |
| 50 | `res_partner_menu_config` | "Configuration", sequence 35, group `base.group_system` |
| 56 | `menu_partner_category_form` | Contact Tags → `base.action_partner_category_form` |
| 61 | `res_partner_industry_menu` | Industries → `base.res_partner_industry_action` |
| 65 | `menu_localisation` | Localization (submenu) |
| 68 | `menu_country_partner` | Countries → `base.action_country` |
| 72 | `menu_country_group` | Country Group → `base.action_country_group` |
| 77 | `menu_country_state_partner` | Fed. States → `base.action_country_state` |
| 82 | `menu_config_bank_accounts` | Bank Accounts (submenu) |
| 87 | `menu_action_res_bank_form` | Banks → `base.action_res_bank_form` |
| 92 | `menu_action_res_partner_bank_form` | Bank Accounts → `base.action_res_partner_bank_account_form` |

Note that **every action behind those menus is defined in `base`, not in `contacts`.**
The live action IDs confirm it (`58`…`64`, `762`).

---

## 3. Dependency graph

```
                       ┌────────────┐
                       │  contacts  │  application=True, depends base+mail
                       └──┬──────┬──┘
                          │      │
                 ┌────────▼──┐ ┌─▼────────┐
                 │   base    │ │   mail   │
                 └───────────┘ └──────────┘
                          ▲
     ┌──────────┬─────────┼───────────┬──────────────┐
     │          │         │           │              │
  account     sale     purchase     stock      phone_validation
     │          │         │           │              │
  sale_stock purchase_stock      stock_account   partner_autocomplete
                                               base_geolocalize
```

None of the business modules **depends** on `contacts`. They depend on `base`, which
owns `res.partner`. Therefore:

- You can uninstall `contacts` and `res.partner` still works everywhere; you only
  lose the standalone app menu and the custom activity icon.
- Installing `contacts` does not install any business logic; it is a UI convenience.
- `mail` must be installed for the Contacts app to exist, because the manifest
  depends on it (and because the form view expects `<chatter/>` and activity widgets).

---

## 4. Model architecture

All models below live in `base` unless stated otherwise.

| Model | Description | Source |
|---|---|---|
| `res.partner` | Contact (company, person, address) | `base/models/res_partner.py:184` |
| `res.partner.category` | Contact Tags (hierarchical, coloured) | `base/models/res_partner.py:139` |
| `res.partner.industry` | Industry (NAICS-style list) | `base/models/res_partner.py:1258` |
| `res.bank` | Bank (BIC/SWIFT directory) | `base/models/res_bank.py:16` |
| `res.partner.bank` | Bank Account of a partner | `base/models/res_bank.py:73` |
| `res.country` | Country + address format + phone code | `base/models/res_country.py:32` |
| `res.country.state` | Fed. State / province | `base/models/res_country.py:198` |
| `res.country.group` | Country group (e.g. EU) | `base/models/res_country.py:171` |

### 4.1 `res.partner` class header

```python
class ResPartner(models.Model):
    _name = 'res.partner'
    _description = 'Contact'
    _inherit = ['format.address.mixin', 'format.vat.label.mixin',
                'avatar.mixin', 'properties.base.definition.mixin']
    _order = "complete_name ASC, id DESC"
    _rec_names_search = ['complete_name', 'email', 'ref', 'vat', 'company_registry']
    _allow_sudo_commands = False
    _check_company_auto = True
    _check_company_domain = models.check_company_domain_parent_of
```

Consequences worth remembering:

| Declaration | Effect |
|---|---|
| `format.address.mixin` | `_display_address()` / `_get_address_format()` machinery (`base/models/res_partner.py:61`) |
| `format.vat.label.mixin` | Renames the `vat` label per company country at view-build time (`base/models/res_partner.py:45`) |
| `avatar.mixin` | `avatar_128/256/512/1024/1920` computed images, gravatar fallback |
| `properties.base.definition.mixin` | The custom "Properties" block on the form |
| `_order = complete_name ASC` | Everywhere partners are listed they come alphabetically by *commercial* name |
| `_rec_names_search` | `name_search` matches complete name, e-mail, reference, VAT and company registry |
| `_check_company_auto` | Every relational field write is validated against the active companies |
| `_check_company_domain = check_company_domain_parent_of` | A record may point to a company that is a *parent* of the record's company |

`mail` then re-inherits it:

```python
# mail/models/res_partner.py:12
class ResPartner(models.Model):
    _name = 'res.partner'
    _inherit = ['res.partner', 'mail.activity.mixin', 'mail.thread.blacklist']
    _mail_flat_thread = False
```

`mail.thread.blacklist` itself inherits `mail.thread`, so a partner gets:
`message_ids`, `message_follower_ids`, `activity_ids`, `activity_state`,
`message_needaction`, `email_normalized`, `is_blacklisted`, …

`_mail_flat_thread = False` means the chatter groups messages into threads by
subject instead of showing one flat list — which is why a partner's chatter can show
separate conversations.

### 4.2 `res.partner.category`

```python
_name = 'res.partner.category'
_order = 'name, id'
```

Fields (`base/models/res_partner.py:148`):

| Field | Type | Notes |
|---|---|---|
| `name` | Char, required, translated | Tag label |
| `color` | Integer | Kanban/tag colour index |
| `parent_id` | Many2one → self | Tags can be hierarchical |
| `child_ids` | One2many → self | Child tags |
| `active` | Boolean | Archive instead of delete |
| `parent_path` | Char | Materialised path for `child_of` |
| `partner_ids` | Many2many → `res.partner` | Relation table `res_partner_res_partner_category_rel` |

The tag tree is used by the Contacts search view with `operator="child_of"`, so
searching a parent tag also finds partners tagged only with its children. Every
contacts list can be opened filtered by tag through the `category_id` context, and
`view_header_get` prints *"Partners: <tag>"* (`base/models/res_partner.py:1159`).

### 4.3 `res.partner.industry`

A flat reference list (`base/models/res_partner.py:1258`):

```python
name      = fields.Char('Name', translate=True)
full_name = fields.Char('Full Name', translate=True)
active    = fields.Boolean('Active', default=True)
```

`industry_id` on the partner is a **commercial field**: it is hidden on child
contacts and delegated to the parent company (see §5.3).

### 4.4 `res.bank` and `res.partner.bank`

`res.bank` is a global bank directory:

| Field | Notes |
|---|---|
| `name`, `bic` | `bic` is indexed and upper-cased on create/write (`base/models/res_bank.py:51`) |
| `street`, `street2`, `zip`, `city`, `state`, `country` | Postal address |
| `email`, `phone`, `active` | Contact data |
| `display_name` | Computed as `"Name - BIC"` (`base/models/res_bank.py:36`) |

`res.partner.bank` is the actual account:

| Field | Notes |
|---|---|
| `acc_number` | Required; searched through `_search_acc_number` |
| `sanitized_acc_number` | Stored compute: non-word characters stripped, upper-cased (`sanitize_account_number`, line 11) |
| `acc_type` | `bank` ("Normal") by default; IBAN detection comes from `base_iban` when installed |
| `acc_holder_name` | Account holder if different from partner |
| `partner_id` | Required, `ondelete='cascade'`, domain restricts to companies or root contacts |
| `bank_id` / `bank_name` / `bank_bic` | Related to `res.bank`, writable |
| `allow_out_payment` | "Send Money" flag used by payment flows |
| `currency_id`, `company_id`, `country_code` | Currency/company context |
| `sequence`, `active`, `note`, `color` | Ordering / archiving / notes |

Constraint (`base/models/res_bank.py:105`):

```python
_unique_number = models.Constraint(
    'unique(sanitized_acc_number, partner_id)',
    "The combination Account Number/Partner must be unique.",
)
```

`_find_or_create_bank_account()` (`base/models/res_bank.py:185`) is the standard
entry point used by payments and imports to attach an account number to a partner
without creating duplicates.

### 4.5 Country models

`res.country` (`base/models/res_country.py:32`):

| Field | Purpose |
|---|---|
| `name`, `code` | ISO name and 2-letter code, both unique |
| `address_format` | Python `%`-template used by `_display_address()`; validated by `_check_address_format` (line 152) |
| `address_view_id` | Optional country-specific address form view |
| `currency_id` | Default currency |
| `phone_code` | Country calling code (used by `phone_validation`) |
| `country_group_ids` | Many2many to `res.country.group` |
| `state_ids` | One2many to `res.country.state` |
| `name_position` | Whether the name prints before/after the address |
| `vat_label` | Country-specific label for `vat` ("TVA", "GST", …) |
| `state_required`, `zip_required` | Address validation flags |

`get_address_fields()` (line 138) parses the `address_format` placeholders with a
regex, which is what makes the address widget adapt to the country.

---

## 5. The company / person hierarchy

This is the part of Odoo that most often confuses people. A `res.partner` is **one
row** that can be a company, a person, or an address belonging to a company.

### 5.1 The three roles of one table

```
res.partner
├── is_company = True      → a company (also a "commercial entity")
├── is_company = False
│   ├── parent_id = False  → an independent individual
│   └── parent_id = <co>   → an employee/contact of that company
└── type = contact | invoice | delivery | other
```

`type` (`base/models/res_partner.py:254`) is the **address type**:

| `type` | Meaning | Label shown |
|---|---|---|
| `contact` | Main contact / company address | "Contact" or "Company Address" |
| `invoice` | Invoice address | "Invoice Address" |
| `delivery` | Delivery address | "Delivery Address" |
| `other` | Any other address | "Address" |

Labels are computed in `_compute_type_address_label` (`base/models/res_partner.py:492`).

The form's first tab (`Contacts`, `base/views/res_partner_views.xml:200`) shows the
`child_ids` kanban, i.e. all addresses/contacts attached to this company. The
inline form for a child lets you pick `type` and, when it is not `contact`, enter a
different postal address; when it *is* `contact`, the address is shared with the
company (see sync rules).

### 5.2 `complete_name` and `display_name`

`_get_complete_name()` (`base/models/res_partner.py:378`):

```python
name = self.name or ''
if self.company_name or self.parent_id:
    if not name and self.type in displayed_types:      # invoice, delivery, other
        name = type_description[self.type]             # e.g. "Delivery"
    if not self.is_company and not context.get('partner_display_name_hide_company'):
        name = f"{self.commercial_company_name or self.sudo().parent_id.name}, {name}"
return name.strip()
```

So:

| Partner | `name` | `complete_name` |
|---|---|---|
| Company | `Apex Logistics Ltd` | `Apex Logistics Ltd` |
| Person, no company | `Patrick` | `Patrick` |
| Person under Apex | `Patrick` | `Apex Logistics Ltd, Patrick` |
| Delivery address, no name | *(empty)* | `Apex Logistics Ltd, Delivery` |

`_order` and the kanban use `complete_name`, which is why lists read
"Company, Person".

`display_name` is computed separately (`_compute_display_name`, line 1036) and is
the value shown in many2one widgets; it respects `show_address` and `show_vat`
context keys used throughout sale/purchase/account forms.

### 5.3 Commercial entity

`commercial_partner_id` (`base/models/res_partner.py:513`):

```python
if partner.is_company or not partner.parent_id:
    partner.commercial_partner_id = partner
else:
    partner.commercial_partner_id = partner.parent_id.commercial_partner_id
```

The commercial entity is the company (or root individual) that owns the commercial
relationship. **Accounting, credit limits, VAT, payment terms and sales/purchase
statistics are all attached to the commercial entity, not to the child address.**

`commercial_company_name` (line 521) is the company name used when printing
addresses: the commercial entity's name if it is a company, otherwise
`company_name`.

### 5.4 Field synchronisation

Two field families are synchronised (`base/models/res_partner.py:684–830`):

| Family | Fields | Direction |
|---|---|---|
| Address fields | `street`, `street2`, `zip`, `city`, `state_id`, `country_id` (`ADDRESS_FIELDS`, line 25) | Up *and* down, but only for children with `type = 'contact'` |
| Commercial fields | `vat` (**synchronised**), `company_registry`, `industry_id` (**delegated**) | `vat` writes up to the parent; all read from the parent on children |

```python
def _commercial_fields(self):
    return self._synced_commercial_fields() + ['company_registry', 'industry_id']

def _synced_commercial_fields(self):
    return ['vat']
```

`_fields_sync(values)` (line 768) is the orchestrator:

1. **From upstream** — if `parent_id` changed, copy commercial values down; if the
   child is `type='contact'` and has a parent, copy the parent's address down.
2. **To upstream** — if a contact's address changed, write it to the parent; if a
   synchronised commercial field changed, write it to the parent.
3. **To downstream** — if this record is the commercial entity, propagate commercial
   fields to all descendants; if its address changed, push it to all `contact`
   children.

`_commercial_sync_from_company` (line 724), `_commercial_sync_to_descendants`
(line 749) and `_company_dependent_commercial_sync` (line 735) implement this,
including propagation to other companies for `company_dependent` fields.

Practical rules:

- Editing the **company address** updates all contact-type children.
- Editing a child that is `type='contact'` writes the address back to the company.
- Editing the **VAT of a child** writes it to the parent company, and vice versa.
- `company_registry` and `industry_id` are only editable on the commercial entity;
  on children they are delegated (read-only by view `invisible` rules).
- Changing `parent_id` triggers `onchange_parent_id` (line 570), which offers to
  copy the parent's address into the child.

`_handle_first_contact_creation()` (line 827) implements a friendly shortcut: when
the first contact of a company is created and the company has no address yet, the
contact's address is promoted to the company address.

### 5.5 Address resolution for documents

`address_get(adr_pref)` (`base/models/res_partner.py:1119`) is called by sales,
purchase, delivery and invoice documents to find the right address of each type:

1. Depth-first search through descendants (stopping at `is_company` nodes).
2. If not found, walk up to the parent company.
3. Anything still missing falls back to `contact`, then to the partner itself.

This is exactly why a sale order can have a different invoice and delivery address
while both belong to the same commercial entity.

---

## 6. Field reference

All fields below are on `res.partner`. "Ext" marks a field added by a module other
than `base`/`mail`.

### 6.1 Identity

| Field | Type | Source | Notes |
|---|---|---|---|
| `name` | Char | `base/models/res_partner.py:213` | Not required at DB level; a `_check_name` constraint requires it for `type='contact'` (line 326) |
| `complete_name` | Char, stored, indexed | computed, line 393 | Alphabetical sort key |
| `is_company` | Boolean | line 277 | Company vs individual |
| `company_type` | Selection `person`/`company` | line 282 | UI radio; computed+inverse (line 633) |
| `parent_id` | Many2one → self | line 215 | "Related Company" |
| `child_ids` | One2many → self | line 217 | Addresses/contacts, `active_test=False` |
| `parent_name` | Char related | line 216 | |
| `function` | Char | line 253 | Job Position (there is **no** `res.partner.title` model in Odoo 19) |
| `employee` | Boolean | line 252 | Marks an employee contact |
| `type` | Selection | line 254 | `contact`, `invoice`, `delivery`, `other` |
| `type_address_label` | Char compute | line 492 | Localised label |
| `ref` | Char, indexed | line 218 | Internal reference |
| `lang` | Selection | line 219 | Defaults from parent (`_compute_lang`, line 398) |
| `tz`, `tz_offset` | Selection / Char | lines 223, 228 | |
| `active` | Boolean | line 251 | Archive flag |
| `color` | Integer | line 286 | Kanban colour |
| `barcode` | Char, company-dependent | line 309 | Badge/barcode identification |
| `website` | Char | line 246 | |
| `comment` | Html | line 247 | "Notes" tab |
| `properties` | Properties | mixin | Custom fields block |

### 6.2 Contact data

| Field | Type | Source |
|---|---|---|
| `email` | Char | `base/models/res_partner.py:272` |
| `email_formatted` | Char compute | line 273 / `_compute_email_formatted` 600 |
| `phone` | Char | line 276 |
| `vat` | Char, indexed | line 237 |
| `vat_label` | Char compute | line 238 / 488 |
| `company_registry` | Char, stored compute+inverse | line 241 |
| `company_registry_label` | Char compute | line 243 |
| `same_vat_partner_id` | Many2one compute | line 239 / 449 |
| `same_company_registry_partner_id` | Many2one compute | line 240 / 449 |
| `industry_id` | Many2one → `res.partner.industry` | line 280 |
| `category_id` | Many2many → tags | line 249 |
| `bank_ids` | One2many → `res.partner.bank` | line 245 |
| `user_id` | Many2one → `res.users` | line 231 (salesperson / account manager) |
| `user_ids` | One2many → `res.users` | line 287 (users attached to this partner) |
| `main_user_id` | Many2one compute | line 288 / 426 |
| `partner_share` | Boolean compute | line 295 / 441 (portal user partner) |

### 6.3 Address

| Field | Type | Source |
|---|---|---|
| `street`, `street2`, `zip`, `city` | Char | lines 263–266 |
| `state_id` | Many2one → `res.country.state` | line 267 |
| `country_id` | Many2one → `res.country` | line 268 |
| `country_code` | Char related | line 269 |
| `partner_latitude`, `partner_longitude` | Float | lines 270–271 |
| `contact_address` | Char compute | line 299 / 504 |
| `contact_address_inline` | Char compute (mail) | `mail/models/res_partner.py:28` |
| `date_localization` | Date ext (`base_geolocalize`) | `base_geolocalize/models/res_partner.py` |

### 6.4 Commercial / accounting (ext `account`)

| Field | Type | Source |
|---|---|---|
| `customer_rank`, `supplier_rank` | Integer | `account/models/partner.py:600-601` |
| `credit`, `debit` | Monetary compute | lines 508, 529 |
| `credit_to_invoice` | Monetary compute | line 511 |
| `credit_limit`, `use_partner_credit_limit`, `show_credit_limit` | Float/Boolean | lines 515–523 |
| `total_invoiced` | Monetary compute | line 533 |
| `days_sales_outstanding` | Float | line 525 |
| `property_account_receivable_id` / `property_account_payable_id` | Many2one, company-dependent | lines 542, 537 |
| `property_account_position_id` | Many2one fiscal position | line 547 |
| `property_payment_term_id` / `property_supplier_payment_term_id` | Many2one payment terms | lines 551, 555 |
| `property_inbound_payment_method_line_id` / `property_outbound_payment_method_line_id` | Many2one | lines 617, 610 |
| `invoice_ids` | One2many `account.move` | line 563 |
| `invoice_sending_method`, `invoice_edi_format`, `invoice_template_pdf_report_id` | Selection/Char/M2O | lines 569–586 |
| `autopost_bills` | Selection | line 602 |
| `trust` | Selection good/normal/bad debtor | line 566 |
| `ignore_abnormal_invoice_date` / `..._amount` | Boolean | lines 567–568 |
| `duplicate_bank_partner_ids` | Many2many related | line 333 |
| `contract_ids`, `ref_company_ids` | One2many | lines 564–565 (plus `bank_account_count`, line 565) |

`account` also overrides `_commercial_fields()` (line 707) to add the fiscal
position/payment terms to the delegated commercial fields, and `can_edit_vat()`
(line 743) so that VAT cannot change on a partner that already has posted
invoices.

### 6.5 Sales (ext `sale`)

| Field | Type | Source |
|---|---|---|
| `sale_order_count` | Integer compute | `sale/models/res_partner.py:10` |
| `sale_order_ids` | One2many `sale.order` | line 15 |
| `sale_warn_msg` | Text | line 16 |

### 6.6 Purchase (ext `purchase`)

| Field | Type | Source |
|---|---|---|
| `purchase_order_count` | Integer compute | `purchase/models/res_partner.py:34` |
| `purchase_warn_msg` | Text | line 39 |
| `buyer_id` | Many2one `res.users` | line 45 |
| `property_purchase_currency_id` | Many2one `res.currency`, company-dependent | line 31 |
| `receipt_reminder_email` | Boolean, company-dependent | line 41 |
| `reminder_date_before_receipt` | Integer, company-dependent | line 43 |

`purchase_stock` adds `on_time_rate`, `purchase_line_ids`, `suggest_based_on`,
`suggest_days`, `suggest_percent`, `group_on`, `group_rfq`.

### 6.7 Inventory (ext `stock`)

| Field | Type | Source |
|---|---|---|
| `property_stock_customer` | Many2one `stock.location`, company-dependent | `stock/models/res_partner.py:11` |
| `property_stock_supplier` | Many2one `stock.location`, company-dependent | line 15 |
| `picking_warn_msg` | Text | line 19 |

These are the "virtual" customer/vendor locations used when a picking is validated.

### 6.8 Telephony (ext `phone_validation`)

| Field | Purpose |
|---|---|
| `phone_sanitized` | E.164-normalised phone, indexed |
| `phone_mobile_search` | Search-only helper for `phone`/mobile |
| `phone_blacklisted` | Opt-out flag for SMS |
| `phone_sanitized_blacklisted` | Combined flag |

`_onchange_phone_validation` (`phone_validation/models/res_partner.py:11`) formats
the number as you type. `phone_validation` also re-declares the mail fields
(`message_ids`, `has_message`, …) so that SMS failure counters exist.

### 6.9 Enrichment and geolocation

| Module | Fields |
|---|---|
| `partner_autocomplete` | no stored partner fields; it enriches through IAP (`autocomplete_by_name` line 86, `autocomplete_by_vat` line 103, `enrich_by_duns` 176, `enrich_by_gst` 183, `enrich_by_domain` 190) |
| `base_geolocalize` | `partner_latitude`, `partner_longitude` (base), `date_localization`; `geo_localize()` at `base_geolocalize/models/res_partner.py:33` |

### 6.10 Odoo 19 removals

| Removed / changed | Replacement |
|---|---|
| `res.partner.title` (`title` field) | Gone. Use `function` (Job Position), a plain Char |
| `is_company` toggle-only UI | `company_type` radio (computed with an inverse, line 633) |
| `display_name` stored | Computed, non-stored |

---

## 7. Methods and behaviours

Line numbers refer to `base/models/res_partner.py` unless stated.

### 7.1 CRUD overrides

| Method | Line | Behaviour |
|---|---|---|
| `default_get` | 201 | Inherits `company_id` from the parent when creating a child; guards against `default_type` leaking from a menu |
| `create` | 925 | Handles first-contact promotion and address/commercial sync; `account` extends it to set customer/supplier ranks |
| `write` | 854 | Refuses to archive a partner linked to an active user; triggers `_fields_sync`; protects invoiced partners' country/VAT |
| `unlink` | — | Standard, but `account` blocks deletion of partners used in journal entries (`_unlink_if_partner_in_account_move`, `account/models/partner.py:787`) |
| `copy_data` | 562 | Appends " (copy)" only when no explicit name is given |
| `name_create` | 1070 | Quick-create from a many2one: parses `"Name <email>"`, stores the e-mail, honours `force_email` in context |
| `find_or_create` | 1093 | E-mail address book resolution used by mail (overridden in `mail/models/res_partner.py:96`) |
| `_load_records_create` | 964 | Import path; also creates the linked `res.users` when importing users |

### 7.2 Archive protection

`write` (line 854) blocks archiving:

```python
self.invalidate_recordset(['user_ids'])
users = self.env['res.users'].sudo().search([('partner_id', 'in', self.ids)])
if users:
    raise UserError(_('You cannot archive contacts linked to an active user.\n'
                      'You first need to archive their associated user.'))
```

`_unlink_except_user` (line 949) is a hook used to protect partners that represent
users from deletion.

### 7.3 Quick company creation

`create_company()` (line 1002) is the "Create" button next to `company_name` on the
form: it creates a company partner for an individual who typed a free-text company
name, and links the individual to it as a child.

`open_commercial_entity()` (line 1021) opens the parent company from a child's form
(used by the "Accounting-related settings are managed on the parent company" link).

### 7.4 Address formatting

| Method | Line | Purpose |
|---|---|---|
| `_address_fields` | 658 | Returns `ADDRESS_FIELDS` |
| `_formatting_address_fields` | 663 | Fields allowed in `address_format` |
| `_get_address_format` | 1172 | Country template or default |
| `_prepare_display_address` | 1175 | Builds the `%`-args dict (`state_code`, `country_name`, `company_name`, …) |
| `_display_address` | 1194 | Renders the final multi-line address |
| `_display_address_depends` | 1207 | Dependency list for the `contact_address` compute |

`_get_default_address_format()` (line 1168):

```python
"%(street)s\n%(street2)s\n%(city)s %(state_code)s %(zip)s\n%(country_name)s"
```

### 7.5 Import helpers

| Method | Line | Purpose |
|---|---|---|
| `get_import_templates` | 1214 | Exposes the import template to the UI |
| `_check_import_consistency` | 1221 | Validates VAT/company-registry duplicates and country/state consistency at import time |
| `_get_country_name` | 1240 | Localised country name |
| `_get_all_addr` | 1243 | All address variants |
| `_get_res_city_by_name` | 1254 | City lookup used by extended address modules |

### 7.6 Vat / company-registry duplicate detection

`_compute_same_vat_partner_id` (line 449) searches for another partner with the same
normalised `vat` or `company_registry`. The form shows a warning alert
(`base/views/res_partner_views.xml:109`) with a clickable link to the duplicate.
This is a **warning, not a blocker**: Odoo still allows the save, because legitimate
duplicates exist (e.g. the same company in two databases merged manually).

`account` adds a second warning for shared bank accounts
(`account/views/partner_view.xml:203`, `duplicate_bank_partner_ids`), displayed
above the form.

### 7.7 Application statistics

`application_statistics` (line 313) is a JSON compute that builds the little badges
shown in the contacts list/kanban footer (e.g. "3 Sale Orders", "2 Invoices").
The hook `_compute_application_statistics_hook` (line 320) is extended by:

- `sale/models/res_partner.py:44` → `fa-usd`, label "Sale Orders"
- `purchase/models/res_partner.py:47` → `fa-credit-card`, label "Purchases"

Each extension checks the user's groups before adding anything, so the badge set is
per-user.

---

## 8. Chatter, activities and blacklist

### 8.1 Tracked fields

`mail/models/res_partner.py:20-25`:

| Field | Tracking order |
|---|---|
| `name` | 1 |
| `email` | 1 |
| `phone` | 2 |
| `parent_id` | 3 |
| `user_id` | 4 |
| `vat` | 5 |

Changing any of these writes a tracking message in the chatter ("VAT: BE… → BE…").
`contact_address_inline` (line 28) is also tracked so address changes appear in the
chatter as inline HTML.

### 8.2 Chatter

The mail view `mail/views/res_partner_views.xml` (record
`res_partner_view_form_inherit_mail`) adds:

- a `<chatter/>` after the sheet, and
- a "remove from blacklist" button next to the e-mail field when
  `is_blacklisted` is true.

Because the partner inherits `mail.thread.blacklist`, the chatter also exposes the
blacklist toggle (mailing opt-out) and the "send SMS" / "log note" / "schedule
activity" actions.

### 8.3 Activities

`mail.activity.mixin` gives the partner:

| Field | Meaning |
|---|---|
| `activity_ids` | Scheduled activities |
| `activity_state` | `overdue` / `today` / `planned` |
| `activity_date_deadline`, `my_activity_date_deadline` | Deadlines |
| `activity_user_id`, `activity_type_id`, `activity_summary` | Assignment |
| `activity_exception_decoration`, `activity_exception_icon` | Visual exception |
| `_get_needaction_count` (`mail/models/res_partner.py:69`) | Badge count |

Activity types available here include the generic `To-Do`, `Call`, `Email`,
`Meeting`, `Document` (plus HR-specific ones when `hr` is installed).

`contacts/models/res_users.py:9` overrides `_get_activity_groups()` so that the
systray entry for `res.partner` activities uses the Contacts icon
(`contacts/static/description/icon.png`) instead of the generic base icon.

### 8.4 Discuss integration

`mail/models/res_partner.py` also provides:

| Method | Line | Purpose |
|---|---|---|
| `_compute_im_status` | 41 | Online/offline presence from `bus` |
| `_mail_get_partners` | 83 | Resolve e-mails to partners |
| `_find_or_create_from_emails` | 119 | Bulk address-book resolution |
| `get_mention_suggestions` | 298 | @mention autocomplete |
| `_get_mention_token` | 247 | Tokenised mention links |
| `_get_store_avatar_card_fields` | 259 | Avatar card in Discuss |

---

## 9. Cross-module extensions

`res.partner` is the most-extended model in the database. Live count of fields per
module for `res.partner` in `newdb`:

| Module | Fields added |
|---|---|
| `base` | 73 |
| `account` | 43 |
| `mail` | 38 |
| `phone_validation` | 16 |
| `account_followup` | 16 |
| `insurance_broker_claims` (custom) | 10 |
| `purchase_stock` | 9 |
| `website` | 9 |
| `account_edi_ubl_cii` | 8 |
| `purchase` | 8 |
| `point_of_sale` | 7 |
| `calendar` | 6 |
| `sale` | 5 |
| `stock` | 5 |
| `hr` | 5 |
| `payment` | 4 |
| `insurance_broker_finance` (custom) | 4 |
| `pos_settle_due` | 4 |
| `delivery` | 4 |
| `product` | 4 |
| `base_geolocalize` | 3 |
| `partner_autocomplete` | 2 |

(Truncated; the total is well over 300 fields.)

### 9.1 Accounting (`account`)

- **Ranks.** `customer_rank` / `supplier_rank` are incremented when a posted
  customer invoice / vendor bill is created (`account/models/account_move.py:5735`).
  They drive the Customers/Vendors menu domains and the "Customers"/"Vendors"
  smart defaults.
- **Receivable/payable.** `_credit_debit_get` (line 366) sums the unreconciled
  receivable/payable move lines whose `partner_id` is that record, in company
  currency. Because documents are normally posted on the **commercial entity**,
  child addresses usually show zero and the parent shows the balance. The `credit`
  and `debit` fields are also searchable (`_credit_search` / `_debit_search`).
- **Fiscal position.** `property_account_position_id` is applied by
  `_get_fiscal_position` (`account/models/partner.py:247`), which is called from
  every invoice/order line to map taxes and accounts.
- **Payment terms.** Default terms for customer invoices and vendor bills.
- **Credit limit.** `credit_limit` + `use_partner_credit_limit`; enforced by the
  sale order confirmation when `account_use_credit_limit` is enabled on the company.
- **Duplicate bank warning.** `duplicate_bank_partner_ids` and the alert.
- **Deletion guard.** A partner referenced by an `account.move` cannot be deleted.
- **Country/VAT lock.** `_can_edit_country` (line 737) and `can_edit_vat`
  (line 743) return `False` once posted documents exist.

### 9.2 Sales (`sale`, `sale_management`)

- `sale_order_count` (computed, group-gated) and the "Sales" smart button.
- `sale_order_ids` for the smart button action
  (`sale.act_res_partner_2_sale_order`).
- `sale_warn_msg` plus `sale.group_warning_sale`: a warning blocks/annotates
  quotation confirmation.
- The salesperson is `user_id`; it is prefilled on new quotations.
- `_compute_credit_to_invoice` (line 83) adds open sale-order amounts to the credit
  used by the credit-limit check.
- `_can_edit_country` / `can_edit_vat` are restricted when an issued sale order
  exists.

### 9.3 Purchase (`purchase`, `purchase_stock`)

- `purchase_order_count` and the "Purchases" smart button.
- `purchase_warn_msg` plus `purchase.group_warning_purchase`.
- `buyer_id` — the default buyer on RFQs for this vendor.
- `property_purchase_currency_id` — supplier currency used on POs.
- `receipt_reminder_email` / `reminder_date_before_receipt` — automatic receipt
  confirmation e-mails.
- `on_time_rate` (from `purchase_stock`) — vendor punctuality KPI.

### 9.4 Inventory (`stock`, `stock_account`)

- `property_stock_customer` / `property_stock_supplier` — destination/source
  locations used when validating a picking
  (`stock/models/stock_picking.py:1001`).
- `picking_warn_msg` — warning shown when validating a transfer
  (`stock/models/stock_picking.py:1017`).
- `action_view_stock_serial()` (`stock/models/res_partner.py:21`) — list of
  lot/serial numbers linked to the partner (smart button, `stock.group_production_lot`).
- The "Inventory" group in the Sales & Purchase tab is only visible in debug mode
  (`base.group_no_one`).

### 9.5 Other installed modules

| Module | Effect on contacts |
|---|---|
| `phone_validation` | Phone formatting, `phone_sanitized`, SMS blacklist |
| `partner_autocomplete` | "Enrich" button on the form; IAP lookups by name/VAT/DUNS/GST/domain |
| `base_geolocalize` | `geo_localize()` writes `partner_latitude/longitude` + `date_localization` |
| `account_followup` | Adds follow-up levels and `payment_next_action_date`-style fields |
| `website` | `website_id`, `website_published`, `visitor`-related fields |
| `point_of_sale` | POS-specific customer flags and the "Edit Partner" action |
| `payment` | Saved payment tokens (`payment.token`) linked to the partner |
| `delivery` | Carrier preferences and destination constraints |
| `hr` | `employee_ids` and employee-related fields |
| `calendar` | Attendee/event relations |
| `insurance_broker_*` (custom) | Broker/claims fields added to the partner |

---

## 10. Interconnections

### 10.1 Link-field matrix

| Target model | Field on target | Direction | Meaning |
|---|---|---|---|
| `account.move` | `partner_id` | M2O | Invoice/bill customer/vendor |
| `account.move` | `partner_bank_id` | M2O | Bank account used for payment |
| `account.payment` | `partner_id` | M2O | Payment counterpart |
| `sale.order` | `partner_id` | M2O | Customer (commercial entity) |
| `sale.order` | `partner_invoice_id` | M2O | Invoice address |
| `sale.order` | `partner_shipping_id` | M2O | Delivery address |
| `purchase.order` | `partner_id` | M2O | Vendor |
| `purchase.order` | `dest_address_id` | M2O | Drop-ship address |
| `stock.picking` | `partner_id` | M2O | Contact on the transfer |
| `stock.move.line` | `partner_id` | M2O | Owner of the goods |
| `stock.lot` | `partner_ids` | M2M | Lots/serials linked to a contact |
| `res.users` | `partner_id` | M2O | The partner *is* the user |
| `res.company` | `partner_id` | M2O | The partner *is* the company |
| `mail.activity` | `res_id` + `res_model` | Reference | Activities on the partner |
| `mail.message` | `res_id` + `res_model` | Reference | Chatter messages |
| `res.partner.bank` | `partner_id` | M2O | Account holder |
| `ir.property` | `res_id` | Reference | Company-dependent commercial fields |

### 10.2 Entity-relationship diagram

```
                        ┌──────────────────────┐
                        │ res.partner.category │
                        │  (name, color,       │
                        │   parent_id)         │
                        └──────────┬───────────┘
                                   │ M2M category_id
                                   ▼
  res.company ──1:1──► ┌───────────────────────┐ ◄──1:N── res.users
   (partner_id)        │      res.partner      │          (partner_id)
                       │                       │
  res.country ◄──M2O── │ country_id            │ ──1:N──► res.partner.bank
  res.country.state ◄─ │ state_id              │            │
  res.partner.industry │ industry_id           │            └──M2O──► res.bank
                       │ parent_id (self)      │
                       │ commercial_partner_id │
                       └───────────┬───────────┘
                                   │
        ┌──────────────┬───────────┼────────────┬──────────────┐
        ▼              ▼           ▼            ▼              ▼
   sale.order    purchase.order  account.move  stock.picking  mail.activity
   (partner_id,  (partner_id)    (partner_id,  (partner_id)   (res_model=
    invoice_id,                  partner_bank)                'res.partner')
    shipping_id)
```

### 10.3 The "one company, many addresses" flow

```
Sale order confirmed
   │
   ├── partner_id          = Apex Logistics Ltd        (commercial entity)
   ├── partner_invoice_id  = Apex Logistics Ltd        (type='invoice')
   └── partner_shipping_id = Apex Logistics, Warehouse (type='delivery')
                                   │
                                   ▼
                       address_get(['invoice','delivery'])
                                   │
              ┌────────────────────┴────────────────────┐
              ▼                                         ▼
        exact type found                        fallback to 'contact'
        (child of the company)                  then to the company itself
```

`address_get` never returns an address belonging to a different commercial entity
unless the user explicitly selected it.

### 10.4 How the partner is used in a document chain

```
Contact (customer)
   │  customer_rank > 0 after first invoice
   ├── Sale order  ──► Delivery ──► Invoice ──► Payment
   │      sale_order_count                total_invoiced / credit / debit
   │
   └── Contact (vendor)
          supplier_rank > 0 after first bill
          Purchase order ──► Receipt ──► Vendor bill ──► Payment
```

All the smart buttons on the contact form read from these chains:

| Button | Field | Action |
|---|---|---|
| Invoiced | `total_invoiced` | `action_view_partner_invoices` |
| Vendor Bills | `supplier_invoice_count` | `account.res_partner_action_supplier_bills` |
| Sales | `sale_order_count` | `sale.act_res_partner_2_sale_order` |
| Purchases | `purchase_order_count` | `purchase.act_res_partner_2_purchase_order` |
| Lots/Serial Numbers | — | `action_view_stock_serial` |

---

## 11. UI navigation

### 11.1 Live menu tree (from `ir_ui_menu`, database `newdb`)

Query used:

```sql
WITH RECURSIVE m AS (
  SELECT id, name, parent_id, sequence, action, web_icon
  FROM ir_ui_menu
  WHERE id = (SELECT res_id FROM ir_model_data
              WHERE module='contacts' AND name='menu_contacts')
  UNION ALL
  SELECT c.id, c.name, c.parent_id, c.sequence, c.action, c.web_icon
  FROM ir_ui_menu c JOIN m ON c.parent_id = m.id
)
SELECT id, parent_id, sequence, name, action, web_icon
FROM m ORDER BY parent_id NULLS FIRST, sequence, id;
```

Result:

| ID | Parent | Seq | Menu | Action | Notes |
|---|---|---|---|---|---|
| 475 | — | 20 | **Contacts** | — | Root app, icon `contacts/static/description/icon.png` |
| 476 | 475 | 2 | Contacts | `ir.actions.act_window,762` | The address book |
| 477 | 475 | 35 | Configuration | — | `base.group_system` only |
| 478 | 477 | 1 | Contact Tags | `…,58` | `res.partner.category` |
| 479 | 477 | 4 | Industries | `…,59` | `res.partner.industry` |
| 480 | 477 | 5 | Localization | — | Submenu |
| 481 | 480 | 1 | Countries | `…,62` | `res.country` |
| 483 | 480 | 2 | Fed. States | `…,64` | `res.country.state` |
| 482 | 480 | 3 | Country Group | `…,63` | `res.country.group` |
| 484 | 477 | 6 | Bank Accounts | — | Submenu |
| 485 | 484 | 1 | Banks | `…,60` | `res.bank` |
| 486 | 484 | 2 | Bank Accounts | `…,61` | `res.partner.bank` |

Note the menu label "Contacts" appears twice: the app (475) and its first item (476).

### 11.2 The Contacts action

`contacts/views/contact_views.xml:3`:

```xml
<record id="action_contacts" model="ir.actions.act_window">
    <field name="name">Contacts</field>
    <field name="path">contacts</field>
    <field name="res_model">res.partner</field>
    <field name="view_mode">list,kanban,form,activity</field>
    <field name="search_view_id" ref="base.view_res_partner_filter"/>
    <field name="context">{'default_is_company': True}</field>
    ...
</record>
```

Consequences:

- Opening the app from the dashboard uses the URL `/odoo/contacts`.
- The **default create mode is "Company"**, because of
  `default_is_company: True`. A user who wants an individual must switch the
  `company_type` radio (or open the simplified form).
- The `activity` view mode is available, so the list can be switched to the
  activity view.

Ordering of the embedded views:

| Sequence | Mode | View |
|---|---|---|
| 0 | list | `base.view_partner_tree` |
| 1 | kanban | `base.res_partner_kanban_view` |
| 2 | form | `base.view_partner_form` |

### 11.3 Other entry points to the same model

Other apps expose partners with their own actions and domains:

| App | Menu | Action | Path | Domain/context |
|---|---|---|---|---|
| Contacts | Contacts | `contacts.action_contacts` | `contacts` | `default_is_company=True` |
| Sales | Customers | `account.res_partner_action_customer` | `customers` | `customer_rank > 0` (search mode `customer`) |
| Purchase | Vendors | `account.res_partner_action_supplier` | `vendors` | `supplier_rank > 0` |
| Invoicing | Customers / Vendors | `account.res_partner_action_*` | `customers` / `vendors` | same actions |
| Point of Sale | Edit Partner | `point_of_sale.res_partner_action_edit_pos` | — | POS-limited fields |
| Website | Partners | `website.visitor_partner_action` | — | Visitors' partners |
| Base (hidden) | Customers | `base.action_partner_form` | — | Internal |

The "Customers"/"Vendors" actions are the **same model** with a different default
filter; nothing is duplicated in the database.

### 11.4 The contact form

Primary view: `base.view_partner_form` (`base/views/res_partner_views.xml:103`).

Layout top to bottom:

1. **Duplicate warnings** (line 109) — VAT / company registry alert.
2. **Button box** — smart buttons injected by `account`, `sale`, `purchase`, `stock`.
3. **Header block**:
   - `company_type` radio (Person / Company)
   - `name` (two fields, one placeholder for a company and one for a person)
   - `email`, `phone`
4. **Left column**:
   - `parent_id` ("Company") with a `res_partner_many2one` widget
   - free-text `company_name` + **Create** button when the company does not exist yet
   - address block: `street`, `street2`, `city`, `state_id`, `zip`, `country_id`
5. **Right column**:
   - `function` (Job Position — only for individuals)
   - `vat` (label from the country)
   - `website`
   - `lang` (only if more than one language is active)
   - `category_id` (tags, coloured)
6. **Properties** block (`properties`, custom fields), two columns.
7. **Notebook** tabs (line 199):

| Tab | Name | Content |
|---|---|---|
| **Contacts** | `contact_addresses` | Kanban of `child_ids` with inline create/edit; address type radio; email/phone/function; address block for non-contact types; internal notes |
| **Sales & Purchase** | `sales_purchases` | *Sales*: `user_id` (salesperson), payment terms, payment method, `sale_warn_msg` group. *Purchase*: `buyer_id`, supplier payment terms/method, `property_purchase_currency_id`, receipt reminder fields, `purchase_warn_msg` group. *Misc*: `company_registry`, `ref`, `company_id`, `industry_id`. *Inventory* (debug only): customer/vendor locations. *Fiscal Information*: `property_account_position_id` |
| **Invoicing** | `accounting` | Only with `account.group_account_invoice` or `account_readonly`, and hidden for child contacts (they show a link to the parent instead). Contains: bank accounts, receivable/payable accounts, auto-post bills, invoice sending method/EDI format/PDF template, credit limits (credit, DSO, limit), and the "abnormal invoice" flags |
| **Notes** | `internal_notes` | `comment` (Html) + `warnings` container where sale/purchase/stock inject their warning fields |

8. **Chatter** — appended by `mail/views/res_partner_views.xml` after the sheet.

The "Invoicing" tab is replaced for child contacts by:

> *Accounting-related settings are managed on **the parent company**.*

with a button calling `open_commercial_entity()`.

### 11.5 Other views

| View | ID / file | Key points |
|---|---|---|
| List | `base.view_partner_tree` (`base/views/res_partner_views.xml:14`) | Name, e-mail, phone, salesperson, street, city, state, country, tags, application statistics |
| Kanban | `base.res_partner_kanban_view` (line 341) | Avatar (with parent company badge overlay for individuals), name, e-mail, phone, city/country, properties, statistics footer |
| Search | `base.view_res_partner_filter` (line 314) | Search by name (on `display_name`), parent company (`child_of`), e-mail, phone, tag (`child_of`), salesperson. Filters: Persons, Companies, Archived. Group by: Salesperson, Company, Country, Properties |
| Simplified form | `base.view_partner_simple_form` (line 39) | Used when creating from a many2one; company type, name, parent, e-mail, phone, job position |
| Address form | `base.view_partner_address_form` (line 67) | Read-only name + address, used for address popups |

`account` also extends the list (EDI columns, hidden by default) and the search
(`account/views/partner_view.xml`, `res_partner_view_search`) with fiscal-position
and invoice-related filters.

### 11.6 Smart buttons per group

| Button | Visible to | Action |
|---|---|---|
| Invoiced (monetary) | `account.group_account_invoice`, `account_readonly` | `action_view_partner_invoices` |
| Vendor Bills | `account.group_account_invoice` (hidden when 0) | Supplier bills list |
| Sales | `sales_team.group_sale_salesman` | Sale orders of the partner tree |
| Purchases | `purchase.group_purchase_user` | POs of the partner |
| Lots/Serial Numbers | `stock.group_production_lot` | `action_view_stock_serial` |
| Saved Payment Methods | `payment` module (`payment_token_count > 0`) | `payment.action_payment_token` |

Each `oe_stat_button` uses `widget="statinfo"`, so the number is the record count of
the corresponding action domain (computed with `child_of`, i.e. including children).

---

## 12. Security model

### 12.1 Menus

| Menu | Groups |
|---|---|
| Contacts (root, 475) | `base.group_user`, `base.group_partner_manager` |
| Contacts (item, 476) | inherited |
| Configuration (477) | `base.group_system` |

`base.group_user` is "Internal User". `base.group_partner_manager` is labelled
**"Creation"** in this database.

### 12.2 Model access (`ir_model_access` on `res.partner`)

| Group (label) | XML ID | Read | Write | Create | Unlink |
|---|---|---|---|---|---|
| Creation | `base.group_partner_manager` | ✔ | ✔ | ✔ | ✔ |
| User: Own Documents Only | `sales_team.group_sale_salesman` | ✔ | ✘ | ✘ | ✘ |
| User | `purchase.group_purchase_user` | ✔ | ✘ | ✘ | ✘ |
| Role / User | `base.group_user` | ✔ | ✘ | ✘ | ✘ |
| Role / Portal | `base.group_portal` | ✔ | ✘ | ✘ | ✘ |
| Role / Public | `base.group_public` | ✔ | ✘ | ✘ | ✘ |
| Administrator | `sales_team.group_sale_manager` | ✔ | ✔ | ✔ | ✘ |
| Administrator | `stock.group_stock_manager` | ✔ | ✔ | ✔ | ✘ |
| Administrator | `purchase.group_purchase_manager` | ✔ | ✔ | ✔ | ✘ |
| Administrator | `account.group_account_manager` | ✔ | ✘ | ✘ | ✘ |

**This is the most surprising rule in Odoo 19 contacts: ordinary internal users
(`base.group_user`) have read-only access to `res.partner`.** Write, create and
delete come from the single "Creation" group (`base.group_partner_manager`), and
only `base.group_system` ("Role / Administrator") implies it:

```sql
SELECT g1.name->>'en_US' AS implies_from, g2.name->>'en_US' AS implies_to
FROM res_groups_implied_rel r
JOIN res_groups g1 ON g1.id=r.gid
JOIN res_groups g2 ON g2.id=r.hid
WHERE g2.id = (SELECT res_id FROM ir_model_data
               WHERE module='base' AND name='group_partner_manager');
-- Role / Administrator → Creation
```

Also note that **no manager row grants `unlink`**: deleting a contact is reserved to
"Creation". In practice this makes archive the normal way to retire a partner.

Group membership in `newdb`:

| Group | Members |
|---|---|
| `base.group_partner_manager` ("Creation") | 1 |
| `base.group_system` | 2 |

So on a default database only administrators can edit the address book. If you want
salespeople to create contacts, add them to "Creation" (Settings → Users → *Access
Rights* → Contacts / Creation), or grant `base.group_partner_manager` from a custom
module.

### 12.3 Record rules

| Rule | Global | Domain |
|---|---|---|
| `res.partner company` | ✔ | `partner_share = False` OR `company_id parent_of company_ids` OR `company_id = False` |
| `res_partner: portal/public: read access on my commercial partner` | ✘ (Portal) | `id child_of user.commercial_partner_id` |
| `res_partner: portal/public: read access on my commercial partner` | ✘ (Public) | same |
| Partner bank company rule | ✔ | `company_id in company_ids + [False]` |
| HR: Prevent non HR officers from accessing employee bank accounts | ✘ (User) | `partner_id.employee_ids = False` |
| Billing: Allow accessing employee bank accounts | ✘ (Invoicing) | always |
| HR: Allow HR officers from accessing employee bank accounts | ✘ (Officer) | always |

The global multi-company rule is the reason a user cannot see a partner created in
a company they are not allowed to access, unless the partner is a *shared* contact
(`partner_share = True`, typically a portal user).

### 12.4 Access to reference data

| Model | Who can write |
|---|---|
| `res.partner.category` | Creation, Administrator |
| `res.partner.industry` | Administrator only |
| `res.bank` | Creation, Administrator |
| `res.partner.bank` | Creation (read for users) |
| `res.country` | Administrator only |
| `res.country.state` | Creation, Administrator |
| `res.country.group` | Creation, Administrator |

This is consistent with the UI: normal users can tag contacts and add bank accounts,
but cannot invent countries or industries.

---

## 13. Data quality: duplicates, merge, archive, import

### 13.1 Duplicate VAT / company registry

- Computed fields `same_vat_partner_id` and `same_company_registry_partner_id`
  (`base/models/res_partner.py:449`).
- The form displays an orange warning with a link
  (`base/views/res_partner_views.xml:109`).
- Saving is **not blocked** — the warning is informational.
- At import time `_check_import_consistency` (line 1221) validates the same
  conditions and can reject rows.

### 13.2 Duplicate bank accounts

`account` computes `duplicate_bank_partner_ids`
(`account/models/res_partner_bank.py:53`) and shows an alert above the partner form
(`account/views/partner_view.xml:203`).

### 13.3 Merge

Odoo 19 ships the merge wizard in the `base` "Merge" action (available from the
list view's Action menu for records with duplicate detection). It relies on:

- `_rec_names_search` for matching,
- `same_vat_partner_id` / `same_company_registry_partner_id` for suggestions,
- Wizards in `base` (`base.partner.merge.automatic.wizard`) that re-point
  `res.partner` references across sale, purchase, account and stock.

Before merging, remember that **accounting entries keep their `partner_id`** unless
the wizard is allowed to reassign them; merging partners with posted invoices is
restricted by `_unlink_if_partner_in_account_move` logic.

### 13.4 Archive vs delete

| Action | Effect |
|---|---|
| Archive | `active = False`; hidden from lists but still referenced by documents. `write` refuses if an active `res.users` points at the partner |
| Delete | Blocked when the partner is referenced by `account.move`, has an active user, or is a company's `partner_id`. Otherwise cascades to `res.partner.bank` |

Archive is the safe option and is what the "Archived" search filter shows.

### 13.5 Import / export

- Import is available on any Contacts list (gear → Import).
- `get_import_templates` (line 1214) provides the template.
- `_rec_names_search` means you can match on `complete_name`, `email`, `ref`, `vat`
  or `company_registry`.
- `name` is `default_export_compatible = True`, so exports always include it.
- Company-dependent fields (payment terms, receivable/payable accounts, stock
  locations, credit limit flags) import **per company**; the importer writes them
  in the current company only.
- Dates and languages come from the user's locale; `lang` is reset to the parent's
  language on children (`_compute_lang`, line 398).

### 13.6 Quick create

`name_create` (line 1070) builds a partner from a single string. It is what happens
when you type a new customer name in a sale order and press *Create*. It parses
`"Name <email>"` into `name` + `email` (and raises if `force_email` is set and no
e-mail was found). It does **not** guess `is_company` and does **not** set
`parent_id`; the record gets whatever defaults the action context provides (the
Contacts action would therefore create a company, but a sale order creates a
person). Use the full form when you need a company hierarchy.

---

## 14. This installation's data snapshot

Query results from `newdb` (snapshot at documentation time):

| Metric | Count |
|---|---|
| `res_partner` rows (all) | 15 |
| Active partners | 8 |
| Companies (`is_company`) | 3 |
| Partners with a parent | 0 |
| Customers (`customer_rank > 0`) | 2 |
| Vendors (`supplier_rank > 0`) | 2 |
| Tags (`res.partner.category`) | 0 |
| Industries | 21 |
| Banks (`res.bank`) | 2 |
| Bank accounts (`res.partner.bank`) | 4 |
| Countries | 251 |
| Fed. states | 2 131 |
| Country groups | 10 |

Active partners:

| ID | Name | Type | Company | Customer rank | Supplier rank |
|---|---|---|---|---|---|
| 1 | My Company | contact | ✔ | 0 | 0 |
| 3 | Administrator | contact | ✘ | 1 | 0 |
| 10 | Apex Logistics Ltd | contact | ✔ | 7 | 0 |
| 11 | SafeGuard Insurance Co | contact | ✔ | 0 | 4 |
| 12 | Jubillee | contact | ✘ | 0 | 1 |
| 13 | PAtrick | contact | ✘ | 0 | 0 |
| 14 | Phillip | contact | ✘ | 0 | 0 |
| 15 | Kevin | contact | ✘ | 0 | 0 |

Observations:

- There are **no child addresses yet** — no invoice/delivery addresses.
- There are **no tags**, so the tag filter is empty and no kanban colour grouping
  will show.
- The three companies have no hierarchical links (`parent_id` is null everywhere),
  so `commercial_partner_id` equals the record itself for all of them.
- Industries are populated by `base` data; only companies can select one in the UI.
- `Administrator` is both a partner and a user (`res.users.partner_id`), which is why
  archiving it is blocked.

---

## 15. Extension points

Where to hook when customising contacts.

### 15.1 Python

| Hook | File | Use |
|---|---|---|
| `_inherit = 'res.partner'` | any module | Add fields/methods |
| `_commercial_fields()` | `base/models/res_partner.py:684` | Make a field delegated to the commercial entity |
| `_synced_commercial_fields()` | line 694 | Make a field synchronised (write-up) |
| `_address_fields()` | line 658 | Add fields to the address sync set |
| `_fields_sync(values)` | line 768 | Override sync behaviour (call `super()`) |
| `_compute_application_statistics_hook()` | line 320 | Add a badge to the contact card |
| `_get_backend_root_menu_ids()` | `contacts/models/res_partner.py:9` | Point "Open in …" elsewhere |
| `_get_activity_groups()` | `contacts/models/res_users.py:9` | Change the activity icon |
| `_compute_same_vat_partner_id()` | `base/models/res_partner.py:449` | Change duplicate detection |
| `_check_import_consistency()` | line 1221 | Add import validation |
| `_display_address()` | line 1194 | Change printed address layout |
| `_get_fiscal_position()` | `account/models/partner.py:247` | Change fiscal position selection |

### 15.2 Views

| View | XML ID | Common xpath |
|---|---|---|
| Form | `base.view_partner_form` | `//page[@name='sales_purchases']`, `//group[@name='warnings']`, `//div[@name='button_box']`, `//notebook` |
| List | `base.view_partner_tree` | `//field[@name='email']` |
| Search | `base.view_res_partner_filter` | `//filter[@name='type_person']` |
| Kanban | `base.res_partner_kanban_view` | `<t t-name="card">` |
| Child kanban | inline in form | — |

The extension pattern used by core modules is worth copying:

```xml
<record id="my_partner_form" model="ir.ui.view">
    <field name="name">res.partner.form.my</field>
    <field name="model">res.partner</field>
    <field name="inherit_id" ref="base.view_partner_form"/>
    <field name="arch" type="xml">
        <xpath expr="//page[@name='sales_purchases']/group" position="inside">
            <group string="My Section" name="my_section">
                <field name="my_field"/>
            </group>
        </xpath>
    </field>
</record>
```

Note that `stock` extends the `mail`-inherited form
(`mail.res_partner_view_form_inherit_mail`), not the base form directly, because
`stock` depends on `mail`. If your module depends on `stock`, inheriting
`base.view_partner_form` still works (the view chain is resolved by priority), but
be explicit about your dependency.

### 15.3 Data

| Data | Model | Notes |
|---|---|---|
| Tags | `res.partner.category` | Provide `parent_id`, `color` |
| Industries | `res.partner.industry` | `noupdate="1"` in core data |
| Banks | `res.bank` | `bic` upper-cased automatically |
| Countries/states | `res.country`, `res.country.state` | Better to install the `l10n_*` module for the country than to create rows |
| Address formats | `res.country.address_format` | Validated by `_check_address_format` |

### 15.4 Do not

- Do not create a second "contact" model. Everything (sale, purchase, accounting,
  stock, mail) is wired to `res.partner`.
- Do not store a company name on a child "for convenience": use `parent_id`, or the
  commercial sync will overwrite you.
- Do not add a `res.partner.title`; the Odoo 19 pattern is `function`.
- Do not `unlink` partners that have documents; archive them.

---

## 16. Verification queries

Run inside the PostgreSQL container:

```bash
docker exec kbmart_postgres_database psql -U odoo -d newdb -c "<query>"
```

Module and version:

```sql
SELECT name, state, latest_version
FROM ir_module_module
WHERE name IN ('contacts','base','mail','account','sale','purchase','stock');
```

Menu tree:

```sql
WITH RECURSIVE m AS (
  SELECT id, name, parent_id, sequence, action
  FROM ir_ui_menu
  WHERE id = (SELECT res_id FROM ir_model_data
              WHERE module='contacts' AND name='menu_contacts')
  UNION ALL
  SELECT c.id, c.name, c.parent_id, c.sequence, c.action
  FROM ir_ui_menu c JOIN m ON c.parent_id = m.id
)
SELECT id, parent_id, sequence, name->>'en_US' AS name, action
FROM m ORDER BY parent_id NULLS FIRST, sequence, id;
```

Field extensions on `res.partner`, grouped by module:

```sql
SELECT m.name AS module, count(*) AS fields
FROM ir_model_fields f
JOIN ir_model_data d ON d.model='ir.model.fields' AND d.res_id=f.id
JOIN ir_module_module m ON m.name=d.module
WHERE f.model='res.partner' AND m.state='installed'
GROUP BY m.name ORDER BY fields DESC;
```

Access rights:

```sql
SELECT g.name->>'en_US' AS grp,
       a.perm_read, a.perm_write, a.perm_create, a.perm_unlink
FROM ir_model_access a
LEFT JOIN res_groups g ON g.id=a.group_id
WHERE a.model_id=(SELECT id FROM ir_model WHERE model='res.partner')
ORDER BY grp;
```

Record rules:

```sql
SELECT r.name, r.global, r.domain_force
FROM ir_rule r
JOIN ir_model m ON m.id=r.model_id
WHERE m.model='res.partner';
```

Duplicate VATs:

```sql
SELECT vat, count(*), array_agg(id), array_agg(name)
FROM res_partner
WHERE vat IS NOT NULL AND vat <> ''
GROUP BY vat HAVING count(*) > 1;
```

Company hierarchy health:

```sql
SELECT p.id, p.complete_name, p.is_company, p.parent_id,
       p.commercial_partner_id, p.type
FROM res_partner p
WHERE p.active
ORDER BY p.complete_name;
```

Bank accounts with the same number:

```sql
SELECT sanitized_acc_number, count(*), array_agg(partner_id)
FROM res_partner_bank
GROUP BY sanitized_acc_number HAVING count(*) > 1;
```

Orphan contacts (child without a company parent):

```sql
SELECT id, complete_name
FROM res_partner
WHERE parent_id IS NULL AND type <> 'contact' AND active;
```

---

## 17. Pitfalls and the mental model

### 17.1 The mental model

```
res.partner  =  one directory entry
     │
     ├── is_company=True            → company / commercial entity
     ├── parent_id=<company>        → an address or employee OF that company
     │      └── type                → contact | invoice | delivery | other
     │
     ├── commercial_partner_id      → the entity that owns the relationship
     ├── complete_name              → "Company, Person"
     └── contact_address            → country-formatted postal address
```

Everything else — sales, purchases, invoices, deliveries, activities — points at
**this row** or at its children. The `contacts` module only paints a menu on top.

### 17.2 Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| Address of one contact changed the company address | The child's `type` is `contact` | Use `type='invoice'`, `'delivery'` or `'other'` for separate addresses |
| VAT not editable on a child | `vat` is a synchronised commercial field | Edit it on the parent company |
| Industry read-only on a person | `industry_id` is a delegated commercial field | Edit it on the company |
| "You cannot archive contacts linked to an active user" | `write` guard at line 854 | Archive the user first |
| Cannot delete a contact | Referenced by an `account.move` or a `res.company` | Archive instead |
| A normal internal user sees contacts but cannot edit/save them | Odoo 19 grants write only to `base.group_partner_manager` ("Creation") | Add the user to Contacts / Creation, or use an administrator |
| Customer does not appear under Sales → Customers | `customer_rank = 0` (no confirmed invoice yet) | Create/confirm an invoice, or filter without the rank domain |
| Duplicate warning on every save | Same VAT/company registry as another partner | Merge or fix the VAT |
| `complete_name` shows "Company, " with a trailing comma | A child with an empty `name` and `type='contact'` | Give the child a name or change its type |
| Chatter "Open in …" goes to the wrong app | `_get_backend_root_menu_ids` not returning Contacts | Check that `contacts` is installed |
| Phone not formatted | `phone_validation` not installed | Install it, or do not rely on `phone_sanitized` |

### 17.3 Impact of uninstalling `contacts`

| Lost | Kept |
|---|---|
| Contacts root menu and its configuration submenus | `res.partner`, all fields, all views |
| Contacts activity icon in the systray | Activities themselves |
| `contacts.action_contacts` | Customers/Vendors actions in Sales, Purchase, Invoicing |

Because no business module depends on `contacts`, uninstalling it is safe — but
users lose their address-book entry point.

### 17.4 Relationship to the main architecture document

The main document
([`odoo-modules-architecture.md`](odoo-modules-architecture.md)) covers how sale,
purchase, inventory and accounting **use** the partner. This document covers the
partner itself. Read them together:

- §4.3 of the main document lists the commercial link fields.
- §9.1 there shows the link-field matrix for documents.
- §12 there explains the group model that this document's §12 applies to contacts.

---

*End of document.*
