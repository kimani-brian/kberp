# KB ERP rollback plan

Use this when go-live must be undone, or when a post-go-live change corrupts
data. The reversal is a restore, not a "delete the new rows" script: posted
moves, valuations and audit records are immutable and interconnected, so
partial cleanup leaves the ledger unbalanced.

## 1. Triggers

Any one of these means stop and invoke rollback:

- Trial balance or balance sheet does not reconcile after cutover.
- Stock quantities differ from the source count and cannot be explained by a
  documented transaction.
- A user group can read or write data outside its mandate.
- A document chain is orphaned (delivery without order, invoice without
  delivery where required, payment without a posted invoice).
- The application cannot start or `/readyz` fails for more than 15 minutes.
- A critical security or data-integrity defect is found during hypercare.

## 2. Decide what to roll back

| Scope | When | Recovery point |
|---|---|---|
| A bad import during the change window | Cutover step 4 or 5 failed | The snapshot taken at cutover step 2, then rerun imports |
| The entire go-live | Step 8 failed or business cannot operate | The pre-cutover snapshot of KB ERP plus the legacy system (which stayed read-only until cutover) |
| A bad deployment after go-live | A release introduced the fault | The last known-good dump plus WAL replay to just before the release |
| A single corrupted document | Isolated data error | Do **not** restore the database; use the domain correction path (reverse the move, cancel or backorder the picking) |

Restoring a database always loses every transaction after the chosen recovery
point. Announce the loss window and get the product owner's approval before
overwriting the live database.

## 3. Rehearsal (required before go-live)

The restore drill exercises the same mechanics against a throwaway database:

```bash
make backup-drill
```

It dumps the live database, restores it into `kberp_restore_drill`, compares
all table counts and sample checksums, and boots the app against the copy.
Record the RPO/RTO lines. A rehearsal that reports mismatches or an RPO/RTO
miss is a release blocker.

## 4. Rollback procedure

1. **Freeze.** Announce the rollback, stop the worker, and put the proxy into
   maintenance mode so no new transactions arrive.

   ```bash
   docker compose stop worker
   ```

2. **Preserve the failed state.** Do not delete anything. Take a snapshot of the
   `db-data` and `wal-archive` volumes and copy the current WAL archive
   somewhere durable. This is the evidence for the post-mortem and the fallback
   if the chosen restore fails.

3. **Choose the recovery point.** For a failed cutover, use the snapshot from
   cutover step 2. For a later incident, replay WAL only to the timestamp just
   before the fault. Never restore over the live database with an unverified
   dump.

4. **Verify the backup on a scratch database first.**

   ```bash
   .venv/bin/python scripts/backup_drill.py --keep
   # inspect kberp_restore_drill, then drop it when done
   ```

5. **Restore.** With the app stopped, restore into the live database:

   ```bash
   PGPASSWORD=$KB_DB_PASSWORD pg_restore -h $KB_DB_HOST -p $KB_DB_PORT \
     -U $KB_DB_USER --clean --if-exists --no-owner --no-privileges \
     --exit-on-error -d $KB_DB_NAME /srv/backups/<chosen-dump>.dump
   ```

   For point-in-time recovery, restore the base backup into a new directory,
   write a `recovery.signal`, set `restore_command` to read the archived WAL,
   set `recovery_target_time` to the chosen timestamp, and start Postgres
   against that directory. Promote it only after the checks below pass.

6. **Verify before reopening.**

   ```bash
   kberp check all
   make check
   kberp check security
   ```

   Then run the reconciliation queries from [`cutover.md`](cutover.md) §4,
   open all five apps, and confirm the outbox is clear before restarting the
   worker and proxy.

7. **Restart and monitor.** Start the worker, then the proxy. Keep the
   ten-minute runbook checks hourly for the first business day.

8. **Return to the legacy system** if the rollback restores KB ERP to its
   pre-cutover state rather than to a usable business state. The legacy system
   remained in place and read-only during the change window; lift the freeze
   there and capture every transaction entered in KB ERP for manual replay.

## 5. After the incident

- Record the timeline, the recovery point actually used, the data loss window,
  and each decision maker in the change log.
- Keep the preserved failed-state volumes until the post-mortem closes.
- Fix the root cause on staging, re-run parity, security, performance and UAT,
  then schedule a new cutover rather than retrying live.
- Update this document and the runbook with anything the incident revealed.
