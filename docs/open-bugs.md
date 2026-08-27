# Open Bugs

Known defects that are intentionally deferred must stay visible here until they
have code, regression tests, and updated documentation. This is not a general
feature wishlist; broader ideas belong in `future-features.md`.

## BUG-001 — Audit pagination cursor is unstable under concurrent appends

- Priority: P2
- Status: Resolved locally on 2026-08-27; stable opaque cursor regressions pass
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
- Status: Resolved locally on 2026-08-27; session-bound authorization regressions pass
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

## BUG-003 — Automatic observations capture transient query intent

- Priority: P2
- Status: Resolved locally on 2026-08-27; durable-context and deduplication regressions pass
- Area: memory extraction, observation promotion, and deduplication

Live UI acceptance testing showed routine questions and search requests being
stored as tentative observations about the user. These entries describe what the
user happened to ask for in one turn rather than durable personal context. They
make the memory review noisy and can later distort retrieval.

Acceptance criteria:

- do not store question-only intent, routine factual searches, tool failures, or
  assistant-authored conclusions as personal observations;
- require durable personal context and semantic novelty before inserting a
  tentative observation;
- continue to retain useful scenario-specific observations without immediately
  promoting them to global facts;
- deduplicate semantically equivalent observations before display and retrieval;
  and
- add regressions proving that transient query intent is not saved while useful
  personal context still is.

## BUG-004 — Search citations expose internal IDs and repeat source labels

- Priority: P3
- Status: Resolved locally on 2026-08-27; compact provenance rendering regressions pass
- Area: searched-answer presentation and provenance rendering

Search answers currently embed strings such as `Source S1` and can repeat a long
source title inside several list items. The provenance remains useful, but the
presentation is difficult to scan and exposes internal source identifiers that
should remain an implementation detail.

Acceptance criteria:

- show compact, human-readable source names without internal `S1`-style IDs;
- avoid repeating the same full source label throughout one answer;
- show URLs only when the user asks for links, while retaining exact provenance
  internally;
- never convert an unverified or model-invented URL into a clickable link; and
- add rendering regressions for ordinary summaries, repeated sources, and an
  explicit request for links.

## BUG-005 — Search can accept topically irrelevant evidence

- Priority: P2
- Status: Resolved locally on 2026-08-27; relevance rejection and retry regressions pass
- Area: automatic provider routing, result ranking, and evidence validation

During live testing, a request for recent news about Iran produced unrelated
academic results about cybersecurity, marketing, and medical screening. The
assistant correctly admitted that the retrieved material was unrelated, but the
search layer should have rejected or retried that result set before synthesis.

Acceptance criteria:

- route current-events requests to at least one enabled provider capable of
  returning recent news;
- score topical and temporal relevance before sources reach answer synthesis;
- retry once with a refined query or another enabled provider when the result set
  is irrelevant;
- return a concise, diagnosable search failure instead of presenting unrelated
  material as the search result; and
- add deterministic regressions for irrelevant result rejection, retry routing,
  and a successful recent-news result set.

## BUG-006 — Session header remains in “stopping response…” state

- Priority: P3
- Status: Resolved locally on 2026-08-27; automated and live cancellation tests pass
- Area: native chat generation lifecycle

The Stop button successfully halts generation, appends `Stopped by you.`, and
re-enables the composer. The session header nevertheless remains stuck on
`stopping response…` after the worker has stopped.

Acceptance criteria:

- transition the session header back to the normal ready state when cancellation
  completes;
- preserve the partial assistant response and `Stopped by you.` notice;
- keep Send enabled after cancellation; and
- add a UI lifecycle regression covering start, stop, worker completion, and the
  final ready state.
