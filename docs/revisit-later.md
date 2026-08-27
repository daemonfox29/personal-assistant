# Revisit Later

Questions and concepts to return to after the project has more working pieces.

Deeper explanations and personal confidence notes live in the
[learning journal](learning-journal.md). This file remains the shorter backlog
of open questions.

## Tool registry and tool execution

The initial registry, native model-call protocol, validation, permission, audit,
and executor path are implemented in Module 2.0. Module 2.1 uses a separate local
SearXNG boundary. Revisit native container installation, start/stop, health,
update review, and provider selection controls after the MVP; also revisit the
trusted UI pause-and-resume experience before the first approval-required tool.

## Model interface and protocols

- What is the `LanguageModel` protocol, and why is it a class rather than a single function?
- How can a model adapter follow the protocol without explicitly inheriting from it?
- What does `@runtime_checkable` verify, and what does it not verify?
- How do replaceable model adapters keep their own settings while sharing the same `generate()` interface?

## Saved memory and database retrieval

- How does the assistant store long-term memory separately from the model's temporary context?
- How does it search saved memory or a database for only the information relevant to a new request?
- When should older conversation be summarized, retrieved from storage, or left out entirely?
