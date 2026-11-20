# ADR 0002 — XML-defined views rendered on the server

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-15 |
| Context | P0 platform |

## Decision

Menus, window actions, client actions and view architectures live in
`core.ir_ui_*` tables, loaded from Odoo-style XML by the installer. The web
layer reads the stored `<list>`, `<form>` and `<search>` arch and renders HTML.
No template contains a hard-coded field list.

The initial renderer is server-side (Jinja2 + Werkzeug). A JSON-RPC surface
(`model.search_read`, `model.read`, `model.create`, `model.write`,
`model.unlink`, `menu.load`) exposes the same metadata to the KWL client that
lands in P0.2.

## Why

- It proves the important contract early: the database, not the template, owns
  the UI definition.
- Server rendering gives working, linkable, testable screens with no build step
  while the client is still being written.
- The same arch can later feed the TypeScript renderer without a migration.
- A test renames a list column in the database and asserts the rendered page
  follows it, preventing template drift.

## Consequences

- Interaction is page-based until the KWL renderer lands; the app switcher and
  dropdowns are progressive enhancement, so no feature depends on JavaScript.
- Inheritance (`inherit_id` + xpath), kanban, x2many and inline editing are not
  implemented yet. They extend the view parser rather than replacing it.
- Every view is validated by `kberp check views`: root element type matches the
  stored type and every field exists on the model.
