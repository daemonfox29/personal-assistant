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
- [Encrypted SQLite provider spike](encrypted-database-spike.md): SQLCipher
  selection, verified guarantees, tradeoffs, and remaining platform checks.
- [Typed memory repository](memory-repository.md): validated payloads,
  revisions, entities, lifecycle, purge, and current access boundaries.
- [Conversation policy](conversation-policy.md): rules governing what the
  assistant says.
- [Project status](project-status.md): current implementation state and session
  handoff notes.
- [Future features](future-features.md): ideas outside the current project step.
- [Revisit later](revisit-later.md): open technical questions to return to.

## Personal learning

- [Learning journal](learning-journal.md): deeper explanations, personal
  progress, and knowledge gaps discovered while building the project.
