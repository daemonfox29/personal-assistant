# Module 1 Persistent Memory Specification

## Status

Design approved for implementation. No personal data may be stored until the
encrypted database boundary, migration checks, typed repository, redacted audit
writer, and focused security tests described here are in place.

## Purpose

Module 1 adds local, restart-persistent memory without turning conversation
history into an unbounded archive or allowing the model to control storage,
retrieval, permissions, or external actions.

The first useful outcome is deliberately small:

1. The user explicitly asks the assistant to remember a low-risk fact or
   preference.
2. Deterministic code validates and stores it in an encrypted local database.
3. A later session retrieves only that relevant record within a strict context
   budget.
4. The user can inspect, correct, supersede, delete, and permanently purge it.
5. Every meaningful operation produces a sanitized audit event without copying
   personal content into the audit log.

## Governing requirements

All implementation and review decisions follow
[Security Principles](security-principles.md). In particular:

- the model proposes; deterministic code validates, authorizes, and writes;
- unknown operations fail closed;
- persistent memory has provenance and cannot grant authority;
- credentials never enter memory, model context, normal tool output, or logs;
- no component may combine unrestricted untrusted input, broad personal-data
  access, and arbitrary external communication;
- consequential actions use exact, recent, one-use authorization; and
- storage, context, retrieval, time, retries, backups, and logs remain bounded.

The design must remain modular and portable across macOS, Windows, and Linux.
Database encryption, key storage, search, backup, audit, and model inference
must be replaceable behind narrow interfaces.

## Scope

### Included in the Module 1 MVP

- an explicitly configured encrypted SQLite-compatible database;
- forward-only, checksummed schema migrations;
- typed records, append-only revisions, provenance, and optimistic concurrency;
- stable entities, aliases, links, scopes, sensitivity, and mention policies;
- explicit remember, inspect, correct, supersede, delete, and purge operations;
- automatic creation of quarantined, unconfirmed memory suggestions;
- bounded deterministic retrieval of confirmed records;
- assembled entity profiles, such as a profile for Luna, without duplicating a
  giant profile record;
- evidence-linked, tentative longitudinal insights;
- sanitized audit events for persistence and retrieval decisions;
- cross-platform encryption and key-provider boundaries;
- one verified encrypted daily backup to a configured external-drive location;
  and
- tests using temporary databases and synthetic information only.

### Deferred

- storing full conversation transcripts;
- cloud synchronization or remote database access;
- multiple users sharing one database;
- vector embeddings or model-specific semantic indexes;
- automatic confirmation of inferred memories;
- automatic deletion of confirmed memories;
- portable import and export;
- unrestricted raw SQL, shell, filesystem, browser, or network access;
- financial-transfer execution; and
- any credential storage, retrieval, derivation, or password inference.

Deferred capabilities are tracked in [Future Features](future-features.md).

## Trust boundaries

### Model

The model may suggest records, links, contradictions, relevance, sensitivity,
or higher risk. Its output is untrusted and cannot directly read or write the
database, lower a deterministic risk classification, issue approval, merge
entities, purge records, change policy, or select arbitrary SQL.

### Memory coordinator

The coordinator converts validated requests into typed repository operations.
It applies status, scope, sensitivity, mention, token, result-count, and risk
rules before any record can reach the model.

### Repository

The repository accepts typed operations and parameterized values only. It owns
transactions, version checks, schema constraints, and deterministic connection
cleanup. It has no model or network access.

### Encryption and key provider

The database provider opens an encrypted database only after receiving key
material from a separate key-provider interface. The database path is explicit;
there is no hidden fallback. Keys never appear in model input, record payloads,
audit metadata, exceptions, command history, or Git.

An implementation spike must verify the selected encrypted SQLite provider on
all intended operating systems before real data is enabled. SQLCipher is the
initial candidate, not an irreplaceable schema dependency.

### Audit sink

The audit sink receives typed, redacted event metadata. It is not canonical
memory and cannot alter allow or deny decisions. Audit failure fails the
personal-data operation closed until the required minimum event can be safely
recorded, except where failing closed would prevent emergency locking or safe
shutdown.

### External capabilities

The memory repository and key provider have no outbound network capability.
Future browser, network, or export components receive only deliberately scoped
data through the executor. They never receive the database handle or key.

## Memory model

### Record kinds

The shared record envelope supports separately validated kinds:

- `fact`: a durable statement about the user or a known entity;
- `preference`: a value or behavior preference with scope and priority;
- `event`: a bounded summary of something that happened, not a transcript;
- `note`: user-directed information that does not fit another kind;
- `insight`: a tentative or confirmed interpretation supported by evidence;
- `policy_preference`: how memory may be mentioned or used within the safe
  policy envelope; and
- `project`, `place`, and `person_or_pet` information represented through
  entities plus linked records.

Adding a kind requires a typed validator, repository methods, retention rules,
sensitivity defaults, retrieval rules, audit events, and focused tests.

### Status

Each record has one current status:

- `candidate`: automatically suggested and quarantined from ordinary retrieval;
- `confirmed`: approved by an explicit user instruction or trusted interface;
- `superseded`: preserved history replaced by a correction or later state;
- `archived`: excluded from ordinary retrieval but still inspectable;
- `deleted`: hidden normal deletion, recoverable through revision history; or
- `purged`: content removed and the opaque identifier placed in the permanent
  deletion ledger.

An explicit instruction such as "remember that Luna turned six in July" counts
as confirmation. Inferred memories remain candidates. Candidates expire from
the review inbox after 30 days unless confirmed, edited, or retained.

### Sensitivity

Sensitivity is independently classified as:

- `normal`;
- `personal`;
- `sensitive`;
- `restricted`; or
- `prohibited`.

Credentials and password-related content are prohibited. They are never
persisted, retrieved, derived, guessed, or used to create password hints.

Restricted emotional or traumatic history is retrieved only when the user
directly invokes it, has configured an applicable mention policy, or confirms a
gentle clarification. Ordinary relevance scoring cannot override this rule.

### Mention policy

Every relevant subject may inherit or override one of these policies:

- `may_mention_when_relevant`;
- `ask_before_mentioning`;
- `only_when_directly_asked`; or
- `never_mention`.

Tightening a restriction takes effect immediately. Loosening a restriction
requires clearer confirmation and, when high risk, the trusted passcode flow.

### Scope

Preferences cascade from least to most specific:

1. global;
2. conversation domain;
3. topic, entity, project, or place; and
4. current session.

The most specific applicable setting wins. A scoped override does not mutate
the global value. Session overrides remain in RAM and disappear unless the user
explicitly saves them.

### Entities, aliases, and profiles

Entities use stable opaque identifiers. Names and aliases are separate records,
allowing "Luna" and "my dog" to point to the same entity without using a name as
identity. Deterministic exact matches may link automatically; ambiguous merges
require clarification.

Profiles are assembled views over current confirmed records and relationships.
They are not duplicated blocks of model-written biography. A Luna profile can
therefore combine age, species, veterinarian, food preferences, medication,
events, and relationships while every fact retains its own provenance,
sensitivity, revision history, and mention policy.

### Longitudinal insights

Insights distinguish:

- observed event summaries;
- explicit user statements;
- tentative model observations; and
- user-confirmed interpretations.

Calling something a pattern requires at least three distinct supporting events.
The candidate insight records its evidence links, time range, plain-language
confidence, contradictions considered, model/provider version, and last review
time. It remains an inference rather than a fact or diagnosis. Uncertainty or
material contradiction triggers clarification.

## Conceptual schema

The initial migrations should create these logical structures. Exact SQL is
defined and tested during implementation.

### `schema_migrations`

- numeric version;
- migration name;
- SHA-256 checksum;
- applied UTC timestamp; and
- application/schema compatibility metadata.

### `records`

- opaque record identifier;
- kind, status, sensitivity, and mention policy;
- scope type and optional scope identifier;
- optional primary entity identifier;
- current revision number;
- valid-from, valid-until, candidate-expiry, created, and updated timestamps;
- optimistic concurrency version; and
- no duplicated historical content.

### `record_revisions`

- record identifier and monotonically increasing revision number;
- validated versioned payload;
- source type and opaque source reference;
- change reason and actor classification;
- optional model/provider version for generated candidates;
- previous-revision hash and current content hash; and
- immutable UTC creation timestamp.

### `entities` and `entity_aliases`

- stable entity identifier and entity type;
- normalized alias plus display form;
- alias provenance and confidence; and
- uniqueness rules that prevent silent ambiguous merging.

### `record_links`

- source and target identifiers;
- typed relationship, including evidence, contradiction, supersession, and
  entity relationships;
- provenance; and
- lifecycle behavior enforced by foreign keys.

### `memory_feedback`

- candidate or record identifier;
- confirm, reject, edit, delete, or relevance-feedback category;
- memory category and non-content scoring metadata; and
- UTC timestamp.

This supports transparent future preference learning without fine-tuning the
language model or allowing it to rewrite policy.

### `deletion_ledger`

- opaque purged identifier;
- purge timestamp and reason code; and
- no deleted personal content.

The ledger is reapplied after restore so an older backup cannot resurrect a
permanently purged record.

## Migration contract

Migrations are packaged numeric, forward-only SQL files. The runner must:

- enable foreign keys and a bounded busy timeout;
- load migrations in fixed numeric order;
- calculate and verify SHA-256 checksums;
- apply each unapplied migration transactionally;
- record it only after successful commit;
- roll back and close connections deterministically on failure;
- reject missing, duplicate, reordered, or checksum-mismatched migrations;
- never guess, edit migration history, delete the database, or silently fall
  back to plaintext; and
- create a verified pre-migration backup before a destructive or compatibility-
  changing migration once real data is enabled.

## Write lifecycle

1. The model or interface proposes a typed candidate.
2. Deterministic code rejects prohibited content, validates size and schema,
   assigns conservative sensitivity, and checks source provenance.
3. The coordinator searches for duplicates, time-based changes, contradictions,
   and ambiguous entities.
4. Ambiguity is clarified rather than guessed.
5. Explicit user remember instructions may create confirmed low-risk records.
   Inferred information creates a quarantined candidate.
6. The repository writes the record and first revision in one transaction using
   an expected version.
7. A sanitized audit event records operation, outcome, IDs, reason codes, and
   duration, but not record content.

Explicit remember requests are handled synchronously. Inferred-candidate
analysis runs only after the visible answer has completed, is bounded and
cancellable, uses at most the completed turn plus the minimum required context,
and cannot delay first-token streaming. It may create only a small configured
number of candidates per turn. Closing the session may safely abandon an
unfinished candidate analysis without changing confirmed memory.

Future automatic confirmation is enabled separately per low-risk category only
after sufficient accepted feedback. The policy and thresholds remain visible,
reversible, and deterministic. Sensitive or restricted categories never gain
automatic confirmation merely because the model is confident.

## Contradictions and revisions

The system never silently overwrites conflicting information. It distinguishes:

- a correction to an inaccurate record;
- a fact or preference that changed over time; and
- a narrower scoped exception.

Corrections append a revision. Changes over time preserve validity dates.
Scoped exceptions coexist according to scope precedence. Material uncertainty
produces a clarification request. Optimistic concurrency rejects stale writes
instead of losing another change.

## Retrieval contract

Storage and retrieval remain separate. A record existing in the database does
not mean it belongs in every model request.

### Natural retrieval depth

- Level 0: current conversation only;
- Level 1: directly relevant confirmed facts and preferences;
- Level 2: related recent events and confirmed insights;
- Level 3: longitudinal patterns when naturally requested; and
- Level 4: restricted or emotionally sensitive history only under its explicit
  access and mention rules.

The user does not need mode commands. Language such as "why does this keep
happening?" may justify Level 3. Ambiguity prompts a natural clarification such
as whether to focus on today or a broader pattern.

### Query stages

The coordinator:

1. applies status, scope, sensitivity, mention, and time filters;
2. matches stable entities, aliases, kinds, and relationships;
3. uses indexed full-text search for remaining text relevance;
4. ranks by specificity, confirmation, relevance, recency, and provenance; and
5. returns only the highest-value records that fit both limits below.

These stages should compile into a small number of indexed database operations,
not separate model calls. Optional semantic retrieval may later rerank the
bounded candidate set behind a replaceable interface.

### Resource and performance limits

Initial defaults:

- at most 12 persistent records per model request;
- at most 2,500 conservatively estimated persistent-memory tokens;
- dynamically reduce memory when the current request requires more context;
- preserve the current 6,000-token session-history ceiling and 2,000-token
  maximum response ceiling within the 16,384-token context window; and
- target p95 database retrieval below 100 milliseconds against 100,000
  synthetic records on the primary development machine, excluding model
  generation and initial database unlock.

Measure median and p95 retrieval latency, records examined and returned, tokens
inserted, database size, missing expected memories, irrelevant retrievals,
unexpected sensitive mentions, and ambiguous entity matches. Content-free
aggregate metrics may be logged; personal query text and results may not.

### Retrieval receipt

The trusted interface may show a concise deterministic explanation containing
selected record IDs, applicable rules, and exclusions. This is not model
chain-of-thought. Example: records about Luna and veterinary care matched; a
restricted record was excluded because it requires a direct request.

## High-risk authentication

Ordinary conversation does not require a separate agent login. Each exact
high-risk operation requires a local passcode or passphrase entered through the
trusted interface, never through chat.

High-risk operations initially include:

- restricted or bulk memory access;
- encrypted export once implemented, and any future plaintext export;
- permanent purge;
- backup restore;
- encryption-key or recovery changes;
- lowering privacy or mention restrictions;
- enabling external, remote, or broad capabilities; and
- changing minimum audit protections.

Failed authentication is rate-limited and audited. Successful authentication
issues only a short-lived, one-use receipt bound to the displayed normalized
operation and arguments. There is no reusable conversational admin mode.
Repeated narrow reads are accumulated within a bounded rolling window and
escalate to bulk-access authorization when their combined exposure crosses the
configured threshold.

Risk classification considers financial, privacy, reputational, mental,
physical, safety, and overall-wellbeing harm caused by error, ignorance,
compromised input, or malice. The model may escalate or express uncertainty but
cannot lower deterministic policy. A passcode proves intent for an otherwise
permitted action; it cannot override permanent denial or required independent
medical, legal, financial, or safety verification.

Foundational doctrine is not a runtime toggle. The owner may deliberately
change source and tests through the development workflow, but the running model
cannot disable its executor, approval, credential, provenance, or default-deny
boundaries through conversation.

Until a trusted passcode entry path exists, high-risk operations are unavailable
from model and conversational interfaces. Tests may exercise their deterministic
authorization contracts with synthetic data; test authority is never shipped as
a production bypass.

## Encryption and transport

- The live database, backups, persisted indexes, and temporary persistent files
  are encrypted at rest.
- Backups and future exports remain encrypted while transferred.
- Any future communication crossing the machine uses authenticated encrypted
  transport.
- Current same-machine Ollama loopback is treated as part of the trusted in-use
  boundary; remote model access requires a separate opt-in adapter and review.
- Data must briefly exist decrypted in process memory while validated,
  retrieved, and used. Minimize amount and lifetime, release references, and
  never claim guaranteed physical erasure from RAM, swap, or crash facilities.
- The optional OS credential-store adapter may support automatic unlock, while
  a separate portable recovery passphrase preserves cross-platform recovery.

Loss of all key material means encrypted data is unrecoverable. Setup and key
rotation must verify recovery material before accepting real records.

## Backup and restore

Initial defaults:

- run once daily when the configured external drive is available;
- retain seven verified encrypted daily snapshots;
- limit one snapshot to 2 GiB and the retained set to 10 GiB;
- warn before coverage would be lost, and never silently replace the last known-
  good backup with an unverified snapshot;
- safely skip and audit when the destination is absent or lacks space;
- use SQLite's consistent online-backup mechanism through the encrypted
  provider rather than copying a live database file; and
- store integrity metadata without personal content.

Restore is a high-risk operation. It must show impact, require the passcode,
create a pre-restore snapshot when safe and space permits, restore to a temporary
location, verify cryptographic integrity and database consistency, run required
migrations, reapply the deletion ledger, atomically replace the live database,
verify the result, and audit the outcome.

## Memory maintenance

The MVP may expire candidates and optimize rebuildable indexes. Later
maintenance may archive transient records, identify duplication, and recommend
cleanup based on age, count, size, and measured retrieval performance.

Maintenance is non-destructive by default. It never silently deletes confirmed
records or removes evidence supporting an insight. Semantic consolidation must
retain links to archived evidence because a generated summary may lose nuance.

## Failure behavior

The system fails closed when:

- encryption or key retrieval fails;
- the database path is missing, ambiguous, or unsafe;
- audit minimums cannot be met for a personal-data operation;
- a migration is missing, reordered, changed, or partially fails;
- a record, payload, source, link, or entity does not validate;
- an optimistic version is stale;
- retrieval would exceed sensitivity, mention, result, token, or time limits;
- a high-risk action lacks an exact valid passcode-backed receipt;
- a backup or restore fails integrity checks; or
- a requested action is unknown or prohibited.

Safe failure preserves the last known-good database, releases connections and
key references, produces a user-safe error, and emits redacted diagnostic
evidence when possible.

## Acceptance tests

No real personal information appears in tests, fixtures, logs, or repository
history.

### Migration and encryption

- Fresh encrypted database migrates to the current schema.
- Re-running migrations is idempotent.
- Missing, duplicate, reordered, or checksum-modified migrations are rejected.
- A failing migration rolls back completely.
- The implementation never falls back to a plaintext database.
- Opening with the wrong key fails without leaking content or key material.
- Connections and temporary artifacts are cleaned up on success and failure.

### Repository and lifecycle

- Writes are parameterized and typed; model-created SQL is impossible.
- Explicit remember creates a confirmed low-risk record and revision.
- Inference creates a quarantined candidate excluded from ordinary retrieval.
- Candidate expiry, confirmation, rejection, correction, supersession,
  archival, deletion, and purge follow the defined state transitions.
- Credentials and password-derived content are rejected.
- Stale expected versions fail without overwriting newer data.
- Purged IDs remain suppressed after restoring an older synthetic backup.

### Retrieval and privacy

- Status, scope, sensitivity, mention, and time filters apply before model
  context assembly.
- Restricted information never appears from ordinary relevance alone.
- Session overrides do not mutate global settings.
- Profiles assemble linked records without duplicating canonical content.
- A pattern requires three distinct evidence links and remains tentative until
  confirmed.
- Record count and token limits hold for oversized result sets.
- Retrieval receipts contain reasons and IDs but no chain-of-thought.
- Synthetic 100,000-record performance tests report the target metrics.

### Authorization and exfiltration resistance

- The model and coordinator cannot obtain a database handle or key.
- The repository cannot make network requests.
- Memory text cannot grant authority or lower policy.
- High-risk actions reject missing, incorrect, expired, replayed, or argument-
  mismatched approvals.
- Model risk output can escalate but cannot downgrade deterministic policy.
- Prohibited actions remain denied after correct passcode entry.
- Audit events contain operation metadata and stable reason codes, not record
  values, credentials, passcodes, prompts, or model responses.

### Backup and recovery

- A consistent encrypted backup can be verified and restored.
- Missing drives, insufficient space, interrupted writes, and corrupt backups
  preserve the live database and last known-good snapshot.
- Retention and size limits remain bounded.
- Restore requires exact high-risk authorization and reapplies the deletion
  ledger.

## Implementation order

1. [x] Implement typed redacted audit events and the bounded local audit writer.
2. [x] Spike and select SQLCipher behind the cross-platform encrypted SQLite and
   key-provider interfaces using synthetic data. Confirm Linux in the batched PR
   run and Windows before distributing a packaged Windows build.
3. [x] Implement the migration runner and initial schema.
4. [x] Implement typed repository operations, revisions, entities, links,
   lifecycle rules, and deletion ledger.
5. [ ] Implement deterministic bounded retrieval and retrieval receipts.
6. [ ] Implement explicit remember and automatic quarantined-candidate workflows.
7. [ ] Implement encrypted daily backup, verification, and guided restore.
8. [ ] Integrate persistent memory into chat only after all preceding boundaries
   and tests pass, then verify restart-persistent recall with synthetic data.

Each step is locally tested and committed. Pushes and pull requests remain
explicit milestones so GitHub Actions usage is not spent on every small change.
