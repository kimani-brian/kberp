# KB ERP operations runbook

Audience: the on-call engineer and the business owner during hypercare. This is
the day-to-day guide; [`cutover.md`](cutover.md) covers the one-time go-live and
[`rollback.md`](rollback.md) covers undoing it.

## 1. What healthy looks like

| Check | Command / URL | Expected |
|---|---|---|
| Process | `docker compose ps` | `db`, `redis`, `web`, `worker` up; db/redis healthy |
| Liveness | `curl -fsS localhost:8069/health` | `ok` |
| Readiness | `curl -fsS localhost:8069/readyz` | database, registry and Redis report ok |
| Metrics | `curl -fsS -H "Authorization: Bearer $KB_METRICS_TOKEN" localhost:8069/metrics` | request count, latency, errors, outbox depth |
| Logs | `docker compose logs --tail=200 web worker` | every request carries an `X-Request-ID`; no tracebacks |
| Build | `make build-id` vs `/readyz` `build_id` vs the top-right stamp | all three equal |
| UI | `make smoke-all` before a demo or release | 21 + 132 + 50 browser checks pass |
| Outbox | `docker compose exec db psql -U kberp -d kberp -c "select state, count(*) from platform.outbox_event group by 1;"` | no growing `pending` backlog; `failed` rows have an `error` |
| Cron | `docker compose exec db psql -U kberp -d kberp -c "select name, next_call from core.ir_cron order by next_call;"` | `next_call` advances; no job stuck in the past |

`/metrics` is closed in production unless `KB_METRICS_TOKEN` is set. Never expose
it through a public load balancer without that token.

## 2. Daily checks (10 minutes)

1. Run the table above and note anything abnormal in the shift log.
2. `kberp check all` against the production replica (read-only): parity and the
   ACL/record-rule audit must report zero findings.
3. Confirm the previous night's dump exists and WAL files are arriving:

   ```bash
   docker compose exec db psql -U kberp -d kberp -c \
     "select archived_count, failed_count, last_archived_wal, last_archived_time from pg_stat_archiver;"
   ```

   `failed_count` must be zero since the last reset and `last_archived_time`
   must be recent (the Compose profile forces a segment every 60 seconds).
4. Check the exporter/monitoring dashboard for a rise in 5xx responses, p95
   latency, or queue depth. Alert thresholds: 5xx > 1 % over 5 min, p95 list
   > 800 ms, post/confirm > 1.5 s, outbox `pending` > 500 for 10 min.

## 3. Backups and restore

The Compose profile archives WAL to the `kberp_wal-archive` volume and sets
`archive_timeout=60`, which bounds point-in-time loss to about one minute
(NFR-008, RPO ≤ 15 min). Production must ship that archive to durable object
storage; a volume on the same host is not a disaster-recovery copy.

Daily full backup (run from the host with PostgreSQL client tools installed):

```bash
PGPASSWORD=$KB_DB_PASSWORD pg_dump -h $KB_DB_HOST -p $KB_DB_PORT -U $KB_DB_USER \
  -Fc --no-owner --no-privileges -d $KB_DB_NAME \
  -f /srv/backups/kberp-$(date +%F).dump
```

Keep at least 14 daily and 2 monthly copies off-host. Retention of business
documents is ten years (NFR-016); the database dump is not the only archive.

Exercise the whole path with the drill (it restores into a throwaway database,
compares all tables and boots the app against the copy):

```bash
make backup-drill
# or: .venv/bin/python scripts/backup_drill.py --keep
```

Record the printed table count, RPO and RTO lines in the change log. The drill
resets archiver counters and forces one WAL switch, so its RPO evidence comes
from the drill itself rather than from history.

For a real point-in-time recovery, use [`rollback.md`](rollback.md). Do not
point the application at a restored database until the reconciliation queries
there have passed.

## 4. Common incidents

| Symptom | Likely cause | Action |
|---|---|---|
| Top-bar menus open nothing | CSS clipping or stale cached bundle | Run `make smoke-menus`; check that the build stamp matches `make build-id`; `make deploy` then hard-refresh |
| Buttons do nothing, pages look old | Stale container or cached bundle | Compare the top-right build stamp with `make build-id`; run `make deploy`, then hard-refresh (Ctrl+Shift+R) |
| `/readyz` fails, db unhealthy | Postgres down or disk full | `docker compose logs db`; check disk; `docker compose restart db`; do not delete WAL files to free space |
| Requests 403 for one user | Group/ACL change or app-level gate | Check `core.res_groups` membership; Accounting requires an accounting group for deep links |
| Outbox `pending` grows | Worker stopped or a handler failing | `docker compose restart worker`; inspect `error` on `failed` rows; fix the handler and let the retry policy re-drive the event |
| Same event processed twice | Handler not idempotent | Handlers must key on `event_id`/document name; compare `platform.outbox_event` and the affected document before retrying |
| Report totals disagree with ledger | Report not re-run after posting | Run `reporting.run` from the report action; the report table is regenerated, not live |
| Back-dated posting rejected | Lock date active | Check Closing → Lock Dates; the correction path is a reversal, not editing a posted move |
| Stock validation fails "insufficient stock" | Reservation or a count changed the quant | Inspect `inventory.quant`; use a backorder or an approved count adjustment, never a direct quant write |
| Slow list after import | Missing sequence/index or oversized page | Confirm page size ≤ 500; `kberp check views`; re-run `scripts/bench_lists.py` |

## 5. Deployment hygiene

- `KB_DEBUG=0`, a unique `KB_SECRET_KEY`, strong `KB_ADMIN_PASSWORD` and a
  dedicated `KB_METRICS_TOKEN` in every production environment. The values in
  `.env.example` are development defaults and must never be shipped.
- Terminate TLS at a reverse proxy in front of the Werkzeug server; the app
  itself listens on plain HTTP inside the Compose network.
- Run the web and worker containers as non-root, keep images pinned by digest
  for production, and apply dependency upgrades on a staging snapshot first.
- Do not share the admin login. Accounting users need an accounting group;
  read-only internal users can read documents but cannot post or approve.
- The audit log, posted moves, secured entries and done transfers are
  immutable. Correct them with reversal, cancellation or backorder flows, not
  direct table writes.

## 6. Escalation

For a suspected data-loss or security incident: stop the worker, preserve the
current database and WAL archive, take a snapshot of the container volumes,
then follow [`rollback.md`](rollback.md). Notify the product owner and tech
lead before any restore that changes the live database.
