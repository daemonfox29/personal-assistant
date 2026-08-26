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

## Audit trail integrations

The bounded, redacted local audit writer described in `docs/audit-logging.md` is
implemented. Integrate its typed events into blocked redirects, permission
decisions, approval receipts, tool execution, and database operations as those
capabilities are built. Each integration needs focused tests proving it does not
record prompts, responses, credentials, URLs, paths, exception text, or personal
record content.

## Post-merge CI verification

If the project risk or GitHub Actions budget increases, add a `push` trigger for
`main` so the test suite verifies the exact merged commit. The current workflow
runs only on pull requests targeting `main`, avoiding a duplicate job for every
merge while the project has a limited Actions budget.

## Windows compatibility verification

Before this assistant is distributed or used with real personal data on
Windows, add an explicit Windows release gate. At minimum, verify on a supported
Windows 11 environment that:

- the pinned Python and SQLCipher packages install without an unencrypted
  SQLite fallback;
- encrypted databases can be created, closed, reopened, migrated, backed up,
  and restored;
- a synthetic encrypted database is readable across macOS and Windows when the
  same key is supplied, while the wrong key and ordinary SQLite both fail;
- Windows path, file-permission, atomic-replace, external-drive, and credential-
  store behavior satisfy the same fail-closed security contract;
- the complete automated test suite passes; and
- installation and recovery instructions are tested by following them from a
  clean machine or virtual machine.

Add Windows CI only at an appropriate release milestone so the current
pull-request workflow does not spend the limited Actions budget on an unused
platform. Treat Windows support as unverified until this gate passes; package
availability alone is not proof of runtime compatibility.

## Reassess the Python dependency workflow

At a later maintenance milestone, reassess whether `uv` is still the right
package and environment workflow for the project. Review its maintenance and
security posture, lockfile behavior, supported Python versions, CI performance,
and macOS, Windows, and Linux installation experience. Compare it with the
then-current `pip` ecosystem and other mature alternatives.

Do not change tools merely because another option is newer. Keep `uv` while it
continues to provide understandable, reproducible, cross-platform environments
with acceptable maintenance cost. Any migration must preserve dependency
pinning, package-hash verification, clean-environment testing, and a documented
rollback path.

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
- configure the cross-platform encrypted database, portable recovery method,
  and operating-system credential-store automatic unlock, including removal or
  re-enrollment of the machine-local credential;
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

Current Module 1 defaults to preserve or expose through that future UI:

- use protected automatic unlock for the native app after one verified recovery
  entry, with manual recovery fallback; keep Windows and Linux credential-store
  behavior unverified until their explicit platform gates pass;
- when the macOS `.app` is signed, migrate from the current Local
  Authentication-before-Keychain sequence to a Keychain item whose own
  `SecAccessControl` requires user presence, then verify Touch ID and Mac-login-
  password fallback in the packaged application;
- do not require a separate login for ordinary conversation; require a local
  passcode or passphrase entered through the trusted interface for each exact
  high-risk operation;
- retain seven verified, encrypted daily backups;
- limit one backup to 2 GiB and the complete retained backup set to 10 GiB,
  with a warning before backup coverage would be lost; and
- show tentative memory suggestions in a review inbox, but exclude them from
  ordinary retrieval until the user confirms them.

High-risk operations should initially include restricted or bulk memory access,
exports, permanent deletion, backup restore, encryption-key changes, lowering
privacy restrictions, enabling external or remote capabilities, and changing
minimum audit protections. The credential must never enter chat, model context,
or logs. Failed attempts must be rate-limited and audited, and successful
authentication must issue only a short-lived, one-use approval for the exact
displayed operation.

Risk classification must consider potential harm to the user's safety,
finances, privacy, mental or physical health, reputation, and overall
wellbeing, whether the risk comes from error, ignorance, compromised input, or
malicious intent. The model may flag uncertainty or recommend a higher risk
level, but it cannot lower the deterministic policy's classification. Unknown
or ambiguous consequential actions fail closed for clarification or stronger
authorization. A passcode proves user intent for an otherwise permitted action;
it does not override a permanent denial or replace independent verification
required for medical, financial, legal, or other consequential decisions.

The interface may adjust behavior within documented safe ranges, including
memory categories, mention policies, retrieval limits, backup schedules, and
enabled registered tools. Foundational invariants are not runtime toggles: the
model cannot issue its own approval, memories cannot grant authority,
credentials cannot enter model context, unknown actions remain denied, and the
executor remains the only route to capabilities. The owner can deliberately
change those invariants through the normal source-review and testing workflow,
but not through a conversational instruction to the running assistant.

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

## Memory sensitivity-policy evaluation

Once the review inbox has enough synthetic and user-reviewed examples, evaluate
the deterministic capture classifier instead of expanding keyword rules by
intuition alone. Track content-free aggregate counts for suggested sensitivity,
policy-raised sensitivity, user tightening, user loosening, candidate
confirmation, rejection, and unexpected sensitive mentions. Never place the
underlying memory text in metrics or audit logs.

The trusted interface should periodically ask:

- Were useful suggestions rejected or made too difficult to confirm?
- Did anything sensitive receive a classification or mention policy that felt
  too casual?
- Are too many ordinary memories being routed into higher-risk review?
- Were duplicate and contradiction prompts understandable and helpful?
- Does the candidate inbox feel useful, noisy, or intrusive?

A future upgraded model may recommend a higher sensitivity or identify nuanced
categories that fixed rules miss, but it cannot lower the deterministic floor.
Changes to the floor require versioned policy review, synthetic regression
cases, and an auditable rollout rather than a conversational instruction.
