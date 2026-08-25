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

Current chat flow, with the optional Module 1 adapter supplied by a trusted
startup path:

User request → bounded encrypted retrieval → untrusted-data system envelope →
token-bounded structured messages → model adapter → local Ollama model →
streamed response

The default command-line startup does not yet supply that adapter because
portable key onboarding and recovery must be implemented before real personal
data is accepted. Without it, the flow remains the Module 0 session-only path.

Future action flow:

User request → coordinator → model and/or tools → permission layer → approved action → result returned to user

## Initial scope

The first version uses one local model and a command-line interface. Recent
conversation is held only in RAM for the current session. System, user, and
assistant messages remain separate data structures; history retains only
complete recent turns within a conservative token budget.

Confirmed persistent records can be selected by the encrypted repository's
deterministic policy and inserted into the system message as one bounded JSON
data object. Stored strings are explicitly untrusted and cannot grant tool or
permission authority. Candidate, restricted, expired, out-of-scope, and
mention-blocked records remain excluded before model context assembly.
The labeling can reduce accidental instruction-following but is not assumed to
make the model reliable; deterministic permission and executor boundaries
remain responsible for preventing actions.

Closing the process drops the application's history references and no
conversation database exists yet. This is an application retention boundary,
not guaranteed physical erasure from Python, Ollama, the operating system,
swap, backups, or crash diagnostics.

Future versions may add bounded worker agents. Worker agents will receive limited tasks and permissions from the coordinator rather than unrestricted access.

## Data boundaries

- Source code, tests, and documentation are committed to Git.
- Secrets, personal data, databases, browser state, logs, and model files remain local and are excluded from Git.
- Audit logs are a diagnostic record, not canonical memory. They must be
  bounded, redacted, local, and independently replaceable.
