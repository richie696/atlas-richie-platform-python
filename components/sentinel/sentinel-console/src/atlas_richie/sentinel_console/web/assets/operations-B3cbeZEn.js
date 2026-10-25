const e=`---
title: Backup, recovery and routine operations
summary: Rehearse on a schedule instead of when something breaks.
prerequisite: An admin account; knowledge of your deployment shape and your
  configuration locations.
outcome: An executable backup list, and a recovery that has actually been rehearsed.
---

## What to back up

Three things have to be backed up separately. None of them contains another, so backing up one does not restore the other two.

| Object                                       | What it contains                                                                              | What happens if you do not back it up                                                          |
| :------------------------------------------- | :-------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------- |
| The Console database                         | Accounts, roles, source registrations, bindings, drafts, versions, publication records, audit | The accounts and the history are gone, and so are the rule publication records                 |
| The deployment-side keys and state directory | Key ring, setup-window state, runtime locator files, first-run lock                           | The encrypted database locator cannot be found, and the source credentials cannot be decrypted |
| The rules in the configuration center        | The rules that are currently in effect                                                        | The runtime has no rules to load                                                               |

> **Note** Audit records have no built-in expiry, and the cleanup command does not cover them. If compliance requires long-term retention, or you need to control the size of this table, archive it yourself outside the Console database.

## How to rehearse the recovery

A recovery procedure that has never been rehearsed is not a backup. These steps can be followed as written.

1. Prepare a backup snapshot in an isolated environment; do not rehearse on production.
2. Restore the Console database and confirm that it starts and that you can log in.
3. Restore the deployment-side keys and state directory and confirm that the encrypted locator files can be decrypted.
4. Confirm that the rule content in the configuration center matches the backup.
5. After logging in, check that the accounts, roles, source registrations and bindings are complete.
6. Check that the version catalog and the publication records are intact.
7. Find a test instance and confirm that the load observation path can be re-established.
8. Record how long the rehearsal took and which step it stalled on.

> **Note** The easiest thing to miss during a rehearsal is the keys and state directory. It is not in the database, but without it the database locator cannot be decrypted.

## What to watch every day

The following are worth confirming regularly in routine operations.

Fault incidents and audit records accumulate continuously and should be reviewed from time to time. The retention period for fault incidents is defined: the current implementation records 30 days per incident, counted from the moment the Collector received it; even if the cleanup job never runs, the queries filter out the expired incidents by logical expiry. The physical deletion is performed on the deployment side with \`sentinel-console incident-events expire\`, which deletes the rows that have expired according to the current UTC time and prints the number of deleted rows, for example \`expired-incidents=12\`; it is safe to run repeatedly. This command deletes the fault incidents only; accounts, rule versions and publication records are outside its cleanup scope. When compliance requires long-term retention, both the audit records and the fault incidents have to be archived outside the Console database, and this cleanup command does not cover them; after the archiving, keep running the cleanup job, the copies are unaffected.

1. Confirm that the source connection probe is still usable. A failed probe directly affects the publication.
2. Confirm that the monitoring targets are still being scraped and that the samples are fresh.
3. Confirm that the Reporter heartbeat has not timed out.
4. Confirm that the setup window is closed.
5. Confirm that the disk space and the log directory are not accumulating.
6. Spot-check the audit records regularly and confirm that unusual operations are visible.

## What a health check proves

A process health check only reflects whether this process can serve requests. It does not check whether the database is reachable, whether the configuration center can be read, or whether the monitoring path has data.

So "the health check is green" must not be read as "the system is healthy". The health of the chains is visible in the probe results on the Connections and collection tab.

| Signal                      | What it proves                              | What it does not prove                                                        |
| :-------------------------- | :------------------------------------------ | :---------------------------------------------------------------------------- |
| The process health check    | The process responds                        | Whether the database, the configuration center and the monitoring are healthy |
| The source connection probe | The configuration center can be reached now | Whether the rule content is correct                                           |
| The monitoring source probe | The monitoring backend can be queried now   | Whether there are samples in this time range                                  |
| The load observation        | A process accepted a snapshot               | Whether requests are really being blocked                                     |
`;export{e as default};
