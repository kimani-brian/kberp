# ADR 0003 — Server-rendered shell first, KWL client second

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-15 |
| Context | P0 platform |

## Decision

P0.1 ships an HTML shell: launcher, app switcher, menubar, breadcrumbs, list,
search, form, chatter and JSON-RPC. P0.2 adds the KWL TypeScript renderers,
client-side router and WebSocket notifications on top. Both clients consume the
same XML metadata and the same RPC methods; the server-rendered pages remain as
the no-JavaScript fallback.

## Why

- The P0 gate is about proving the platform end to end, not about framework
  ceremony. A working HTML product validates the ORM, loader, ACLs, outbox and
  launcher sooner and gives the test suite a stable surface.
- Business phases C1/S1/A1 can start against a known-good server contract once
  P0.2 lands, without waiting for a second renderer to be perfect.
- The design tokens (`design.md`) are implemented in plain CSS, so the visual
  system is shared rather than duplicated per client.

## Consequences

- Two rendering paths must stay honest. The RPC contract is tested now; the KWL
  renderers will be tested against the same fixtures.
- The app switcher, menus, keyboard shortcuts and flash messages are already in
  `kberp.js`; the KWL client can replace them incrementally without changing
  routes or URLs.
- WebSocket/Redis fan-out is deferred to P0.2. The bus will publish the same
  outbox events that the worker already delivers, so no producer changes.
