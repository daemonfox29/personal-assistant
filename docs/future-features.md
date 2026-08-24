# Future Features

Ideas to revisit after the current project step is complete. Add new ideas here as they arise, without needing to interrupt the current work.

## Safer feature scaffolding

Create a small development command that prepares the repetitive parts of adding a new assistant tool or action:

- an action label;
- a permission-policy placeholder;
- a unit-test skeleton;
- a documentation checklist.

The command must not choose a permission level automatically. A person must explicitly decide whether the action is allowed, requires approval, or is denied.

## Policy-completeness checks

Add an automated test that fails when an action label exists without an explicit permission rule and corresponding test coverage.

The current unknown-action fallback remains `DENY` for safety. The completeness check will make an unfinished feature visible during development instead of silently leaving it in that fallback state.

## Future workflow goal

When a feature is added, use automation to create the standard project pieces while requiring a deliberate review of its security policy before the feature is treated as complete.

## Approval interface

After the Module 0.1 approval-receipt foundation is in place, build a small trusted interface that clearly shows the exact action and arguments before the user approves it. Its approval receipt should be one-use and short-lived, so an assistant cannot silently reuse a previous approval for a different action.

## Local audit trail

Implement the bounded, redacted local audit writer described in
`docs/audit-logging.md` before tools or personal-data operations are enabled.
The audit trail should diagnose blocked redirects, permission decisions,
approval receipts, tool execution, and database operations without recording
prompts, responses, credentials, or personal record content by default.

## Post-merge CI verification

If the project risk or GitHub Actions budget increases, add a `push` trigger for
`main` so the test suite verifies the exact merged commit. The current workflow
runs only on pull requests targeting `main`, avoiding a duplicate job for every
merge while the project has a limited Actions budget.

## Memory, privacy, and backup settings interface

Add a non-technical configuration interface for persistent memory after the
Module 1 data boundary is implemented. It should let the user:

- search and inspect confirmed memories, tentative suggestions, linked entity
  profiles, sources, and revision history;
- see a concise, deterministic explanation of why a memory was retrieved,
  without recording or exposing model chain-of-thought;
- confirm, correct, reject, edit, delete, or permanently purge a memory;
- configure global and subject-specific mention policies, including
  `may mention when relevant`, `ask before mentioning`, `only when directly
  asked`, and `never mention`;
- view effective settings after global, conversation, topic, and session
  overrides are applied;
- configure a cross-platform encrypted database and portable recovery method,
  with optional operating-system credential-store integration;
- choose an external-drive backup destination, run or schedule one daily
  backup, set retention and size limits, verify backup health, and perform a
  guided restore; and
- review sanitized audit events for memory changes, backup operations, and
  restores without exposing personal record contents.

The first backup policy should favor one verified daily snapshot to an
external drive. Backups must remain encrypted, excluded from Git, bounded by a
configurable storage limit, and restorable across macOS, Windows, and Linux.
Before a restore, create a pre-restore snapshot when space permits, verify the
candidate backup, explain what will change, require explicit approval, and
reapply the permanent-deletion ledger so purged records are not resurrected.

Initial defaults:

- offer automatic unlock through the current operating system's credential
  store, while retaining a separate portable recovery passphrase;
- retain seven verified, encrypted daily backups;
- limit one backup to 2 GiB and the complete retained backup set to 10 GiB,
  with a warning before backup coverage would be lost; and
- show tentative memory suggestions in a review inbox, but exclude them from
  ordinary retrieval until the user confirms them.

## Portable encrypted import and export

After the Module 1 memory MVP is working, add a versioned, cross-platform
import and export format. Exports must be encrypted by default both while
stored and while transferred. Import must validate the schema version, data
types, size, integrity, and provenance before changing the live database.
Plaintext export, if it is ever supported, must require an explicit warning and
approval and must never be the default.

## Memory maintenance and model-upgrade review

Investigate a non-destructive maintenance process for large memory stores. It
may expire unconfirmed suggestions, archive transient records outside normal
retrieval, consolidate redundant records, rebuild indexes, and recommend
cleanup when configured count or size thresholds are reached. It must not
silently delete confirmed memories or remove evidence supporting an insight.
Permanent deletion remains an explicit user action and must update the purge
ledger.

Keep canonical records, relationships, provenance, and revisions independent
of any one language model or embedding format. A future upgraded model may
reassess existing records and propose more nuanced tentative insights, while
preserving the original evidence and recording the model/version that made the
proposal. Derived indexes and embeddings must remain replaceable and
rebuildable.
