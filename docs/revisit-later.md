# Revisit Later

Questions and concepts to return to after the project has more working pieces.

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
