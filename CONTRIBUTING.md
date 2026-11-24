# Contributing to KB ERP

Thanks for taking a look. KB ERP is an Odoo-shaped ERP for contacts, sales,
purchase, inventory and accounting. The project is built phase by phase; the
plan and the exit criteria for each phase live in [`phases.md`](phases.md), and
the current evidence lives in [`BUILD.md`](BUILD.md).

## Before you start

- Read [`rules.md`](rules.md). It defines module boundaries, coding rules and
  business invariants that the test suite enforces.
- Read [`architecture.md`](architecture.md) for the stack, request flow, ORM and
  service layers.
- For anything larger than a bug fix, open an issue first so the change can be
  tied to a phase or a documented gap. Unsolicited large rewrites are unlikely
  to be merged.

## Development setup

You need Python 3.12, Node.js 20 or newer, Docker, and a PostgreSQL 16 client if
you want to inspect the database directly.

```bash
cp .env.example .env
make install         # Python venv with dev dependencies
make client-install  # KWL client npm dependencies
make db-up           # PostgreSQL 16 on localhost:5433
make init            # schemas, tables, XML metadata and demo data
make run             # http://localhost:8069 (admin / admin)
```

The full gate before a pull request is:

```bash
make check           # ruff, mypy, client typecheck/build, parity, pytest
```

`make check` needs the database up. For UI changes, also run the browser suites
against a running stack:

```bash
make deploy
make smoke-all
```

## Making a change

1. Branch from `main`: `git checkout -b fix/short-description`.
2. Make the smallest change that solves the problem. Keep unrelated refactors
   out of the pull request.
3. Add or update a regression test. A bug fix without a test that fails before
   the fix is not complete.
4. Rebuild the client bundle if you changed `client/src/`; CI rejects a stale
   `src/kberp/web/static/js/kwl.js`.
5. Run `make check` and make sure it passes.
6. Open a pull request using the template, describing what changed, why, and the
   evidence you ran.

## Coding standards

- Python is formatted and linted with Ruff at a 100-character line length, and
  type-checked with mypy. Do not add blanket `# type: ignore` comments.
- A module may import only its declared dependencies. Business data is reached
  through services, never through another module's tables.
- New metadata belongs in the addon's XML files (menus, actions, views), not in
  ad-hoc Python lists.
- Keep the UI copy production-shaped. No build-phase labels, placeholder
  screens or internal phase names in user-facing text.
- Never commit `.env`, credentials, customer data or generated runtime files.
  Use `.env.example` for new settings.

## Tests

The pytest suite runs against a throwaway database (`kberp_test_ci`) that is
rebuilt once per session. Browser tests live in `client/smoke.mjs`,
`client/menus.mjs` and `client/controls.mjs` and need a running stack plus
Chrome.

When you add a test, name it after the behaviour it protects. Tests for a phase
go in the matching `tests/test_*.py` file and are also listed in `BUILD.md`.

## Commits and pull requests

- Write commit subjects in the imperative mood: `fix: reject a negative
  quantity on receipt`, not `fixed receipt bug`.
- Keep one logical change per commit. Squash fixups before requesting review.
- Pull requests should be small enough to review in one sitting.
- Describe the verification you ran, including commands and results.

## Security reports

Do not open a public issue for a suspected vulnerability. Follow
[`SECURITY.md`](SECURITY.md) instead.

## Licensing

A project license has not been chosen yet. Until it is, contributions are
accepted for inclusion in this repository, but you should not assume the code
can be redistributed under an open-source license. Open an issue before
contributing if that matters to you.
