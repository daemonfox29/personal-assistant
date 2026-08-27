# Open Bugs

Known defects that are intentionally deferred must stay visible here until they
have code, regression tests, and updated documentation. This is not a general
feature wishlist; broader ideas belong in `future-features.md`.

## BUG-001 — Audit pagination cursor is unstable under concurrent appends

- Priority: P2
- Status: Open; deferred until after the next Module 1.5 pull request
- Area: local audit reader and native Audit trail page

The current newest-first reader uses a numeric offset. If a background operation
appends audit events between page requests, older rows shift relative to that
offset. The next page can repeat boundary events and reduce the number of unique
events visible within the 1,000-event ceiling.

Acceptance criteria:

- replace the offset with an opaque stable boundary derived from trusted event
  ordering data;
- preserve newest-first bounded reads across rotations;
- prove that appends between page requests produce neither duplicates nor gaps;
- keep event identifiers and cursor internals out of visible UI columns; and
- retain symbolic-link refusal, malformed-entry detection, and the 1,000-event
  display ceiling.

## BUG-002 — Session-only mode can read redacted owner audit history

- Priority: P2
- Status: Open; deferred until after the next Module 1.5 pull request
- Area: application-service composition and native Settings authorization

The application service currently receives the local audit path even when
persistent memory was not unlocked. A session-only user can therefore view
content-minimized operational timestamps, components, actions, outcomes, and
reason codes. The view does not expose prompts, memories, paths, or identifiers,
but owner operational history should still follow the persistent-session unlock
boundary.

Acceptance criteria:

- do not expose an audit path or audit inventory when the encrypted owner session
  is locked or bypassed;
- show a clear unavailable state in session-only Settings;
- preserve ordinary owner access after successful persistent-memory unlock; and
- add tests covering configured-but-locked, explicit session-only, and unlocked
  sessions.
