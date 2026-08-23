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

Current Module 0 chat flow:

User request → command-line interface → token-bounded structured messages → model adapter → local Ollama model → streamed response

Future action flow:

User request → coordinator → model and/or tools → permission layer → approved action → result returned to user

## Initial scope

The first version uses one local model and a command-line interface. Recent
conversation is held only in RAM for the current session. System, user, and
assistant messages remain separate data structures; history retains only
complete recent turns within a conservative token budget.

Future versions may add bounded worker agents. Worker agents will receive limited tasks and permissions from the coordinator rather than unrestricted access.

## Data boundaries

- Source code, tests, and documentation are committed to Git.
- Secrets, personal data, databases, browser state, logs, and model files remain local and are excluded from Git.
- Audit logs are a diagnostic record, not canonical memory. They must be
  bounded, redacted, local, and independently replaceable.
