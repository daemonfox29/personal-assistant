# Encrypted Database Migrations

The Module 1 schema is created by a deterministic migration runner in
`personal_assistant.migration`. It receives an already verified encrypted
connection provider; it cannot open ordinary SQLite or choose a database path.

## Safety contract

- SQL files are packaged with the application and named with contiguous,
  three-digit versions such as `001_schema_migrations.sql`.
- Each file contains exactly one SQL statement. Transaction commands inside a
  migration are rejected because the runner owns the transaction.
- SHA-256 is calculated over the exact packaged bytes. The version, name,
  checksum, application compatibility label, and UTC application time are
  stored in `schema_migrations`.
- Stored history must be an exact prefix of the packaged history. A gap,
  duplicate, reordering, renamed migration, altered checksum, unknown newer
  version, malformed ledger, or existing untracked schema fails closed.
- All pending migrations run in one transaction. Any failure rolls back the
  complete pending batch and leaves the previously committed schema unchanged.
- The runner never repairs history, deletes a database, guesses intent, or
  falls back to plaintext SQLite.
- Migration audit events contain only the operation, outcome, reason code,
  count, duration, and a fixed target label—not SQL, paths, keys, or record
  content.

Once a migration is committed to shared history, do not edit, rename, reorder,
or remove it. Make every later schema change by appending the next numbered SQL
file and adding focused forward- and failure-path tests.

## Initial schema boundary

The initial migrations create the ledger plus the structural tables described
in the approved memory specification: records, append-only revisions, entities,
aliases, record links, memory feedback, and the permanent deletion ledger.
They also create narrow lookup indexes for later bounded retrieval.

This schema does not by itself authorize persistence. There is still no chat
integration and no real personal data is stored. Typed repository validators,
lifecycle operations, retrieval policy, backup/recovery, and their tests remain
required before persistent memory can be enabled.
