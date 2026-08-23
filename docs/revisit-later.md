# Revisit Later

Questions and concepts to return to after the project has more working pieces.

Deeper explanations and personal confidence notes live in the
[learning journal](learning-journal.md). This file remains the shorter backlog
of open questions.

## Tool registry and tool execution

- How does the Python program define the set of tools available to the LLM?
- How is that approved tool list shown to the LLM?
- How does an LLM request a tool rather than directly performing an action?
- How does Python validate the request, check permissions, ask for approval, and only then run the real tool?

## Model interface and protocols

- What is the `LanguageModel` protocol, and why is it a class rather than a single function?
- How can a model adapter follow the protocol without explicitly inheriting from it?
- What does `@runtime_checkable` verify, and what does it not verify?
- How do replaceable model adapters keep their own settings while sharing the same `generate()` interface?

## Saved memory and database retrieval

- How does the assistant store long-term memory separately from the model's temporary context?
- How does it search saved memory or a database for only the information relevant to a new request?
- When should older conversation be summarized, retrieved from storage, or left out entirely?
