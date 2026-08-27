# Module 2 Tool Registry and Execution Specification

## Purpose

Module 2 gives the assistant narrow deterministic capabilities without giving
the language model direct access to Python, the operating system, files, the
network, credentials, approvals, or internal authority objects.

The model may propose a structured call to a code-owned registered tool. The
coordinator and executor validate, authorize, audit, execute, and bound that
request. Tool output returns to the model as explicitly untrusted data before
the model writes its user-facing answer.

This specification follows `security-principles.md`. When a useful capability
cannot satisfy those rules, it remains disabled.

## Approved Module 2.0 scope

The first slice implements the complete request path with two read-only local
tools:

- `get_current_datetime`: returns the machine's current local date, time, UTC
  offset, and time-zone label;
- `calculate`: performs one bounded binary decimal operation selected from add,
  subtract, multiply, and divide.

Neither tool reads files, accesses memory or credentials, contacts a network,
launches a process, changes state, or evaluates model-provided code. Web search
is the next separately reviewed Module 2.1 capability.

## Explicitly excluded

Module 2.0 does not enable:

- shell commands, Python evaluation, SQL, arbitrary expressions, or plugins;
- filesystem or project-file access;
- browser navigation, web search, downloads, or other network requests;
- email, calendar, financial, medical, smart-home, or account actions;
- credential access or secret-bearing tool results;
- model-issued approvals or approval receipts inside prompts;
- parallel tool execution, background agents, delegation, or recursive tasks;
- runtime tool installation or model-authored tool schemas; or
- persistent permission grants stored in chat or memory.

## Components and authority

### Model adapter

The Ollama adapter translates immutable code-owned tool definitions into the
native `/api/chat` `tools` field. It validates returned `tool_calls` into bounded
typed values. It never executes a call.

Ollama documents native function schemas, structured assistant `tool_calls`, a
separate `tool` message role, and tool calling during streaming:

- <https://docs.ollama.com/api/chat>
- <https://docs.ollama.com/capabilities/tool-calling>

### Registry

The registry is constructed from trusted source code. Each unique tool name is
bound to exactly one immutable model-facing definition, existing `ActionKind`
permission classification, deterministic argument validator, and narrow
implementation callable.

Unknown and duplicate names fail closed. The model receives only definitions,
not callables, policy objects, audit sinks, or credentials.

### Coordinator

The conversation service is the initial coordinator. For each model step it:

1. supplies only enabled registry definitions;
2. streams and accumulates typed model output;
3. refuses more than one call in one step;
4. sends one validated call to the executor;
5. appends one bounded `tool` result as untrusted data; and
6. asks the model for the final user-facing answer.

The coordinator cannot execute a handler directly. A loop has at most three
tool steps per user request. Repeated, parallel, malformed, or excessive calls
produce fixed safe results and stop at the resource ceiling.

### Executor

The executor is the only route to a registered callable. For each call it
resolves the code-owned entry, validates and canonicalizes arguments, applies
the deterministic permission policy, verifies exact approval when required,
audits, invokes only the resolved callable, and validates the bounded result.

Module 2.0 registers only `ALLOW` tools. An approval-required tool remains
unexecutable until a later trusted UI pause-and-resume approval workflow is
specified and tested. A model statement that approval occurred is ignored.

## Tool contracts

### `get_current_datetime`

Input is an empty object. Additional fields are invalid.

Output contains only an ISO 8601 local datetime to whole-second precision, a
bounded time-zone label, and a numeric UTC offset. The clock is replaceable in
tests. The result reveals the machine time zone to the local model, but not
location services, IP-derived location, or a configured home address.

### `calculate`

Input contains exactly:

- `operator`: `add`, `subtract`, `multiply`, or `divide`;
- `left`: one finite bounded JSON number; and
- `right`: one finite bounded JSON number.

Booleans, strings, NaN, infinity, excess precision or magnitude, division by
zero, extra fields, and missing fields are rejected. Python `eval`, `exec`, AST
evaluation, shell arithmetic, and model-generated expressions are never used.
Decimal arithmetic produces a bounded canonical string result.

## Model and conversation rules

- Native structured tool calls are separate from ordinary assistant text.
- Tool definitions and follow-up results count against a conservative context
  reserve.
- Ordinary no-tool responses continue streaming.
- Preliminary assistant text before a tool call may be displayed, but cannot
  grant authority or prove execution.
- Only visible assistant text is retained as the assistant side of the
  conversation turn; internal tool-role messages are request-scoped.
- Tool results are labeled untrusted and cannot modify system policy, approve an
  action, or become a credential channel.
- Tool output is sanitized and size-bounded before it reaches model context.
- A tool failure produces fixed code-owned error data without exception text.

## Resource limits

Initial hard ceilings:

- two enabled tool definitions;
- one tool call per model step;
- three tool steps per user request;
- four KiB of canonical arguments per call;
- two KiB of canonical result data per call;
- bounded decimal magnitude and precision; and
- no retries inside an individual tool implementation.

The user can cancel by closing the application; graceful shutdown continues to
wait for the active bounded request. Future blocking or external tools require
cancellable process or I/O boundaries before registration.

## Audit requirements

Every proposed execution produces typed events with a shared correlation ID.
Events may record the action kind, tool class, outcome, reason code, duration,
and bounded counts. They must not record prompts, assistant text, arguments,
results, time-zone labels, calculated numbers, exception text, approval tokens,
or arbitrary model-provided names.

Audit failure before execution fails closed. Module 2.0 tools are read-only, so
a success-audit failure cannot leave mutated external state. Future mutating
tools require an explicit transactional or independently verifiable completion
design.

## Acceptance criteria

Module 2.0 is complete only when tests prove:

1. every registered tool has one explicit `ActionKind` policy;
2. duplicate and unknown tool names cannot execute;
3. malformed, oversized, non-finite, and extra arguments fail closed;
4. the calculator never evaluates code and enforces magnitude, precision, and
   division limits;
5. the time tool uses a replaceable aware clock and accepts no arguments;
6. allowed tools execute without an approval receipt;
7. denied or approval-required tools cannot execute without exact authorization;
8. receipts and authority objects never enter model requests or tool results;
9. Ollama requests contain only code-owned schemas and parse bounded calls;
10. ordinary responses still stream when no tool is requested;
11. a tool call returns through a distinct tool-role message before the final
    response;
12. parallel calls, unknown calls, and loops beyond the ceiling are refused;
13. tool messages do not persist as normal conversation roles or memory facts;
14. audit events contain no arguments, results, prompts, or exception details;
15. terminal and native interfaces share the same coordinator behavior; and
16. the full local suite and Linux pull-request gate pass.

## Module 2.1 gate: read-only web search

Web search does not inherit approval merely because Module 2.0 works. Its design
must separately cover explicit network enablement, query and result bounds,
protocol and redirect rules, domain and download handling, prompt injection,
source provenance, citations, timeouts, cancellation, content sanitization,
private-address blocking, audit minimization, and the boundary between search
and browser control.
