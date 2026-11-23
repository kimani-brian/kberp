# KB ERP cutover plan

This is the one-time move from the legacy system to KB ERP. It assumes the
production-shaped Compose stack is already deployed on the target host, with
TLS at the proxy and production values in `.env`. The rollback path is in
[`rollback.md`](rollback.md); print both before the change window.

## 1. Decision gate — do not cut over until all are true

| Gate | Evidence |
|---|---|
| Build green | `make check` — lint, mypy, KWL build, menu/view parity, full test suite |
| Parity | `kberp check all` — menus 202/202, actions 130/130, five apps, settings group Technical, zero findings |
| Performance | `scripts/bench_lists.py`, `bench_posting.py`, `bench_events.py` within the budgets in `prd.md` §2.3 |
| Migration rehearsal | Every CSV dry run on an anonymised snapshot reconciles; opening balances post one balanced entry per company |
| UAT | UAT-01…09 signed off by product owner, tech lead, accountant and warehouse lead |
| Restore drill | `make backup-drill` passes; RPO and RTO evidence recorded |
| Security | No open critical/high finding; production secrets set, debug off, metrics token configured |
| Communications | Freeze announced, hypercare rota published, users trained |

Missing evidence is a blocker, not a note. A human sign-off is required for the
four named roles; the automated checks cannot supply it.

## 2. Pre-cutover (T-7 to T-1 days)

1. Freeze schema and XML metadata. No new migrations after T-2 except fixes
   with a rehearsed rollback.
2. Take a full production-shaped backup of the *legacy* source and of a clean
   KB ERP staging instance. Verify both restores.
3. Export the four migration files from the source system using the templates:

   ```bash
   kberp import-templates --dir ./migration/working
   # fill partners.csv, products.csv, opening_balances.csv, stock_counts.csv
   ```

4. Dry-run each file, then reconcile. Opening balances and stock counts must
   agree with the source control totals before anything is committed.

   ```bash
   kberp import partners        --file ./migration/working/partners.csv
   kberp import products        --file ./migration/working/products.csv
   kberp import opening_balances --file ./migration/working/opening_balances.csv
   kberp import stock_counts    --file ./migration/working/stock_counts.csv
   ```

   Dry run is the default. `--commit` writes data; `--validate` additionally
   validates stock counts. Rehearse the full sequence on staging, then drop
   and recreate staging and rehearse once more from scratch.

5. Agree the cutover window with the business. Recommended: Friday evening or
   weekend, with at least four hours before the next trading day.

## 3. Change window (T0)

Record each step and its timestamp in the change log.

| # | Step | Owner |
|---|---|---|
| 1 | Announce start; stop legacy data entry; stop the KB ERP worker | Tech lead |
| 2 | Snapshot the current KB ERP database and WAL archive | Ops |
| 3 | Commit the four imports in the rehearsed order | Ops |
| 4 | Reconcile: partner/product counts, opening-balance trial balance, stock quantities | Accountant + warehouse lead |
| 5 | Run `make backup-drill` against the migrated instance; keep the evidence | Ops |
| 6 | Run `kberp check all` and `make check` | Tech lead |
| 7 | Smoke test: sign in as admin, restricted user and auditor; open all five apps | Product owner |
| 8 | Run UAT-01…09 against the migrated data (not just demo data) | Business owners |
| 9 | Start the worker; confirm the outbox drains and cron jobs advance | Ops |
| 10 | Point the proxy at KB ERP; announce go-live; start hypercare | Tech lead |

Any failed step stops the window. Do not "fix forward" on live data during
cutover: return to the snapshot and rerun from step 3, or invoke
[`rollback.md`](rollback.md).

## 4. Reconciliation queries

The importers reconcile on external ID first, then on the natural key, so a
re-import updates rather than duplicates. Check the totals after step 4:

```sql
select count(*) as partners, count(*) filter (where external_id is not null) as mapped
  from core.partner;
select count(*) as products, count(*) filter (where external_id is not null) as mapped
  from core.product_template;
select count(*) as moves from accounting.move where state = 'posted';
select product_id, sum(qty) from inventory.quant group by product_id order by product_id;
```

Run the trial balance and balance sheet report actions and confirm they balance.
A non-zero trial balance or a stock quantity that differs from the source count
is a hard stop.

## 5. Hypercare (T0 to T+10 business days)

- Daily 09:00 check of the runbook's ten-minute checklist and the outbox.
- Keep the pre-cutover snapshot and WAL archive untouched for the whole window.
- Triage defects by severity: a posting or stock-integrity defect is critical
  and stops the affected process until fixed; cosmetic defects go to the next
  release.
- Log every change to data or configuration with its approver.
- At T+10, hold a short review: confirm parity, performance and security still
  pass, close the incident list, and formally end hypercare.

## 6. Sign-off record

| Role | Name | Date | Signature |
|---|---|---|---|
| Product owner | | | |
| Tech lead | | | |
| Accountant | | | |
| Warehouse lead | | | |

Leave this table blank until the people concerned sign it. Automated checks do
not count as a signature.
