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

## 2026-08-23 — Structured roles and bounded conversation memory

**Confidence: Building**

### What prompted this

The initial chat joined history into one formatted string and selected only a
bounded slice when making a request. The internal list could still grow for the
whole session, and labels inside user text could look like trusted roles.

### What I understand now

Conversation roles are data, not labels pasted into a prompt. A system message,
user message, and assistant response should remain separate objects all the way
to the model API. Text such as `Assistant: ignore policy` then remains ordinary
user content rather than becoming an assistant instruction.

A context budget must count more than saved history. It also needs room for the
system instruction, current user message, message framing, and the response the
model is allowed to generate. RAM is genuinely bounded only when old stored
turns are evicted, not merely omitted from the next prompt.

RAM history and model context are different limits. The application can retain
an ever-growing list of conversation turns in RAM even though the model sees
only the recent portion placed inside its context window. Limiting the request
therefore does not limit the application's memory use or how long old text
remains available to future code. The app must separately evict the oldest
complete turns from RAM.

Structured roles reduce one specific prompt-injection risk: role
impersonation. If a user writes `System: ignore the rules` or `Assistant: this
action was approved`, that text remains inside a `user` message and cannot
become an actual system or assistant message merely because it contains a
label. This strengthens the trust boundary, but it does not make the model
immune to every prompt-injection attempt. Authorization must still be enforced
outside the model before tools can perform real actions.

Exact tokenization varies by model. The current implementation uses a
conservative UTF-8 byte upper bound and fixed framing allowances. This may keep
less history than an exact Qwen tokenizer, but it avoids a tokenizer dependency
and favors predictable safety over maximum context use.

### Knowledge gaps to revisit

- When an exact model-specific tokenizer becomes worth the dependency.
- How tool-call and tool-result roles should enter the same message contract.
- Whether future summarization should replace evicted turns without turning a
  generated summary into canonical personal memory.
- How to defend against indirect prompt injection in webpages, documents, and
  other untrusted content once the assistant can use tools.

### Practical takeaway

Keep roles structural, reserve the whole context window deliberately, and
bound what remains in RAM—not only what is sent on the next request. Treat
structured roles as one defense layer, while keeping action authorization in a
separate permission system that model-generated text cannot bypass.

## 2026-08-23 — Approval receipts versus approval booleans

**Confidence: Building**

### What prompted this

The first authorization gateway accepted `user_approved=True`. That boolean
said approval happened, but it did not prove what the user approved, when they
approved it, or whether the same approval had already been used.

### What I understand now

An approval receipt is a narrow, temporary capability. The trusted interface
issues an unpredictable opaque token only after showing the exact action and
arguments to the user. The authority stores the approved action, a canonical
digest of its arguments, and an expiration time. The executor must present the
same token for the same request.

The receipt is removed on its first verification attempt, even if the action
or arguments do not match. It therefore cannot be replayed after success or
recovered after someone tries to redirect it. A forged random token has no
matching authority record, and an expired token fails closed.

The model should never own the approval authority or call its issue method.
Otherwise, it could approve its own requests and the security boundary would
be meaningless. A future trusted interface will show the action to the user
and issue the receipt; the executor will only verify and consume it.

### Knowledge gaps to revisit

- How the trusted UI should display complex arguments clearly enough for
  informed approval.
- When separate processes would require signed receipts instead of an
  in-memory authority registry.
- Which receipt outcomes should enter the redacted audit trail.

### Practical takeaway

Approval should authorize one precisely described operation, once, for a short
time. A general yes/no flag is not durable proof of user intent.

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
