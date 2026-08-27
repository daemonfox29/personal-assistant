# Documentation

This folder holds human-readable notes about the assistant's design, decisions, and operating principles.

## Project references

- [Architecture](architecture.md): components, boundaries, and information flow.
- [Security principles](security-principles.md): the threat assumptions and
  decision rules that govern every capability.
- [Audit logging](audit-logging.md): safe diagnostic events, redaction, and
  future local audit-trail requirements.
- [Module 1 persistent memory](module-1-memory-spec.md): approved encrypted
  storage, retrieval, revision, backup, authorization, and acceptance-test
  contract.
- [Module 1.5 native UI](module-1-5-ui-spec.md): lean PySide6 presentation
  boundary, setup/unlock/chat slice, and desktop release gates.
- [Module 2 tool registry](module-2-tools-spec.md): deterministic registry,
  executor, safe local tools, limits, auditing, and the web-search gate.
- [Module 2.1 read-only web search](module-2-1-web-search-spec.md): fixed-host
  local open-source SearXNG provider, user-derived outbound queries, injection
  boundaries, citations, timeouts, auditing, and acceptance tests.
- [Module 2.2 bounded public page reading](module-2-2-public-page-reading-spec.md):
  request-scoped numbered-result reading, public-address pinning, extraction
  limits, and the current-events synthesis gate.
- [Encrypted SQLite provider spike](encrypted-database-spike.md): SQLCipher
  selection, verified guarantees, tradeoffs, and remaining platform checks.
- [Typed memory repository](memory-repository.md): validated payloads,
  revisions, entities, lifecycle, purge, and current access boundaries.
- [Conversation policy](conversation-policy.md): rules governing what the
  assistant says.
- [Project status](project-status.md): current implementation state and session
  handoff notes.
- [Open bugs](open-bugs.md): confirmed defects intentionally deferred with
  acceptance criteria.
- [Future features](future-features.md): ideas outside the current project step.
- [Revisit later](revisit-later.md): open technical questions to return to.

## Personal learning

- [Learning journal](learning-journal.md): deeper explanations, personal
  progress, and knowledge gaps discovered while building the project.
