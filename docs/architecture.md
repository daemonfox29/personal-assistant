# Architecture Overview

## Purpose

This project is a local-first personal AI assistant. It should be useful on one Mac today while remaining modular enough to change models, interfaces, and tools later.

## Core rule

The language model can suggest an action, but it cannot perform an external or sensitive action on its own.

A separate permission layer decides whether an action is allowed. Sensitive
actions must present a short-lived, one-use receipt issued after a trusted
interface shows the user the exact action and arguments.

All components and future capabilities must follow the threat assumptions and
review questions in [Security Principles](security-principles.md).

## Main components

- Interface: how I communicate with the assistant.
- Coordinator: receives a request and decides what should happen next.
- Model adapter: communicates with the selected language model, initially through Ollama.
- Memory adapter: reads and writes assistant memory.
- Data layer: stores canonical personal data in SQLite.
- Tool layer: defines actions the assistant may request, such as reading a local file or using a browser.
- Permission layer: evaluates requested actions and consumes an exact-match
  approval receipt when appropriate.
- Audit layer: records sanitized security decisions and workflow outcomes with
  correlation identifiers, without storing conversation or personal content by
  default.
- Browser adapter: future authenticated browser workflows, with manual login and no credentials stored in memory or logs.

## Information flow

Current native or recovery-CLI chat flow after trusted Module 1 setup and
recovery unlock:

Native widgets or recovery CLI → narrow application/conversation service →
bounded encrypted retrieval → untrusted-data system envelope → token-bounded
structured messages → model adapter → local Ollama model → sanitized streamed
display events

The default command-line startup supplies the adapter only when a safe portable
security manifest exists and the hidden recovery prompt unlocks it. A new or
disabled installation follows the Module 0 session-only path. Explicit remember
instructions are intercepted before model submission. After the visible answer,
a bounded worker may ask the model for tentative suggestions. Deterministic code
may promote only an exact low-risk quote found in the user's current message and
stores that quote with trusted-interface provenance. Model-authored paraphrases,
inferences, sensitive material, and conflicts enter only the quarantined
candidate inbox until trusted review confirms them.

Future action flow:

User request → coordinator → model and/or tools → permission layer → approved action → result returned to user

## Initial scope

The first native interface uses PySide6 widgets over a narrow application
service. Widgets do not receive database connections, keys, approval authorities,
audit sinks, or model adapters. The terminal interface remains a recovery and
developer fallback over the same conversation service. Recent conversation is
held only in RAM for the current session. System, user, and assistant messages
remain separate data structures; history retains only complete recent turns
within a conservative token budget.

Because the native widgets and application service share one Python process,
this narrow API is a modularity and review boundary rather than a sandbox against
malicious UI implementation code. The shipped UI remains trusted code while all
user/model-controlled content is untrusted. A future third-party or lower-trust
interface requires a separate authenticated process and least-authority IPC.

Confirmed persistent records can be selected by the encrypted repository's
deterministic policy and inserted into the system message as one bounded JSON
data object. Stored strings are explicitly untrusted and cannot grant tool or
permission authority. Candidate, restricted, expired, out-of-scope, and
mention-blocked records remain excluded before model context assembly.
The labeling can reduce accidental instruction-following but is not assumed to
make the model reliable; deterministic permission and executor boundaries
remain responsible for preventing actions.

Closing the process drops the application's session-history references. Module 1
stores selected confirmed memories and revision history, not a transcript of
every conversation. This is an application retention boundary, not guaranteed
physical erasure from Python, native libraries, Ollama, the operating system,
swap, backups, or crash diagnostics.

Future versions may add bounded worker agents. Worker agents will receive limited tasks and permissions from the coordinator rather than unrestricted access.

## Data boundaries

- Source code, tests, and documentation are committed to Git.
- Secrets, personal data, databases, browser state, logs, and model files remain local and are excluded from Git.
- Audit logs are a diagnostic record, not canonical memory. They must be
  bounded, redacted, local, and independently replaceable.
