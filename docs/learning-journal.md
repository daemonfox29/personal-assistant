# Learning Journal

This journal tracks concepts learned while building the assistant, questions
that led to deeper discussion, and knowledge gaps worth revisiting. It is about
personal understanding rather than project completion.

## How to use this journal

Add an entry when a design choice, bug, or code review leads to a useful deeper
explanation. Each entry should record:

- the situation that prompted the discussion;
- the concept in plain language;
- what is now understood;
- what still feels uncertain; and
- where the concept appears in this project.

Use these informal confidence labels:

- **New:** I have encountered the idea but cannot yet explain or apply it.
- **Building:** I understand the main idea and can follow it in this project.
- **Comfortable:** I can explain the tradeoffs and make a reasonable design
  choice with it.

The labels are snapshots, not grades. Update them as understanding grows.

## 2026-08-23 — Streaming, full generation, and honest test doubles

**Confidence: Building**

### What prompted this

GitHub Actions failed on Python 3.11 even though the tests passed locally. The
chat tests used unrestricted `Mock` objects. Python 3.11 could mistake those
flexible mocks for models that support streaming, causing the tests to enter a
different response path than intended.

### What I understand now

The model can return an answer in two ways:

- `generate()` waits for the complete answer and returns it at once.
- `stream_generate()` yields small chunks so a person can see the answer while
  it is being produced.

The current Ollama/Qwen terminal chat supports both and normally chooses
streaming. Full generation remains useful for programmatic work where the
application must receive, parse, validate, approve, or save a complete result
before continuing. Structured tool requests and database-ready summaries are
examples.

A test double should represent the exact capability being tested. A plain
`Mock()` can pretend to have almost any attribute. `Mock(spec=LanguageModel)`
limits the fake to the basic non-streaming model contract, while dedicated
streaming test models cover the streaming path. This preserves coverage of both
behaviors instead of changing tests merely to make them pass.

### Why both paths stay in the project

- Streaming is the best fit for responsive, human-facing terminal chat.
- Full generation is the best fit when code needs a complete result before it
  can safely proceed.
- The basic `LanguageModel` contract gives future adapters a small interface to
  implement.
- Streaming remains an optional capability for adapters that support it.

### Where this appears

- `src/personal_assistant/model.py` defines the basic and streaming contracts.
- `src/personal_assistant/chat.py` chooses the path supported by the adapter.
- `src/personal_assistant/ollama_adapter.py` implements both paths.
- `tests/test_chat.py` uses capability-specific test doubles.

### Knowledge gaps to revisit

- How structural `Protocol` checks work at runtime and why their interaction
  with mocks changed between Python versions.
- When `Mock(spec=...)`, `spec_set`, and `create_autospec()` are each the best
  choice.
- How a future coordinator should distinguish conversational streaming from a
  complete structured response used for a tool request.
- How partial output, validation failures, cancellation, and retries should be
  handled during streaming.

### Practical takeaway

Do not weaken or remove a test only because it fails in CI. First identify the
behavior the test intends to represent, then make the test double accurately
model that behavior. If production code remains, its important behavior should
remain tested.

## 2026-08-23 — Context windows, response ceilings, and audit trails

**Confidence: Building**

### What prompted this

The assistant needs concise responses today, a larger context window on a
future desktop machine, and enough diagnostic history to explain blocked or
illegitimate operations.

### What I understand now

The context window and response limit are different controls. The context
window contains the system instruction, conversation history, current message,
and generated response. The response ceiling limits only the generated portion.
The current 16K context window—and a future 32K setting—can therefore provide
more room for instructions and history while retaining a 2,000-token maximum
answer.

Natural-language requests to the model are advisory. A token ceiling enforced
by the application is a real resource boundary. Defaults and individual
requests can be adjusted below that boundary without allowing a prompt or
future agent to bypass it.

An audit trail should record security decisions and outcomes, not copy all
application content. Structured identifiers and reason codes make operations
traceable, while redaction, rotation, retention, and control-character
sanitization prevent the log from becoming a privacy or security problem.

### Knowledge gaps to revisit

- How token counting differs among model tokenizers.
- How the application should reserve input and output space dynamically.
- How append-only or tamper-evident local audit logs work.
- How to choose useful retention and rotation limits for a personal assistant.

### Practical takeaway

Increase context capacity and response length independently. Log enough
structured metadata to explain decisions, but keep prompts, personal content,
credentials, and unsafe raw strings out of routine audit events.

## Entry template

Copy this section for future entries:

```markdown
## YYYY-MM-DD — Topic

**Confidence: New | Building | Comfortable**

### What prompted this

### What I understand now

### Why it matters

### Where this appears

### Knowledge gaps to revisit

### Practical takeaway
```
