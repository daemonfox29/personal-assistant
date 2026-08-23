# Project Status

This document is the handoff point between coding sessions. At the end of each session, update the current status, outstanding actions, and session history below.

## Current status

- Module 0 is complete: Git safety rules, project documentation, source layout, virtual environment, project metadata, a local model adapter, and a runnable chat are in place.
- The local permission policy is implemented and covered by automated tests.
- GitHub Actions is configured to test pull requests targeting `main` before
  merge. Repository branch protection still needs to require the `Tests / test`
  check and block direct pushes. Post-merge runs are intentionally deferred to
  conserve the current Actions budget.
- Runtime personal data, browser state, secrets, logs, databases, and model files remain excluded from Git.
- The assistant has a replaceable language-model interface and a local Ollama adapter configured for `qwen3:14b`.
- Starting the command-line assistant starts Ollama if needed, preloads the local model, uses a 16K context window, caps normal responses at 400 tokens, and asks Ollama to unload the model after five idle minutes.
- Shared defaults and machine-local environment overrides are centralized in `config.py`.
- The local-only chat streams responses and has session-only conversation memory while it is open. It has no persistent memory, tools, browser access, personal-data access, credential access, or web capability.
- Conversation policy is documented separately from the action-permission policy.
- The Ollama adapter and service health check now accept only explicit numeric
  loopback HTTP addresses, ignore environment proxies, and refuse redirects.
- The shared model request contract enforces a 2,000-token response ceiling;
  normal, long, and machine-local defaults remain configurable beneath it.

## Outstanding actions

Work through these in order unless project needs change. Module 1 must wait until the Module 0.1 hardening work below is complete.

- [x] Module 0.1: enforce a truly local-only Ollama connection. Accept only an explicit loopback HTTP address, and prevent proxy use and HTTP redirects. Keep a future remote-model adapter separate and opt-in.
- [ ] Module 0.1: make session memory genuinely bounded in RAM, using a token-aware budget that includes the system instruction and current user message. Define predictable handling for one message that is too large.
- [ ] Module 0.1: replace the temporary `user_approved=True` switch with a one-use, short-lived approval receipt tied to the exact requested action and arguments. Only a trusted interface may issue it; the executor must verify it.
- [x] Module 0.1: enforce the 2,000-token response ceiling in the shared model adapter, not only in the command-line chat interface.
- [ ] Module 0.1: move conversation history to structured `system`, `user`, and `assistant` messages before adding tools, so user text cannot impersonate another role.
- [ ] Module 0.1: sanitize control characters from model output before printing it to the terminal. Add friendly error handling for unavailable Ollama, missing models, malformed responses, and interrupted startup.
- [ ] Module 0.1: make warm-up lightweight, improve documentation wording about privacy and in-memory clearing, extend secret-file ignore rules, and harden the GitHub Actions workflow (full action SHA pins and least-privilege checkout settings).
- [ ] Module 0.1: add focused tests for every hardening rule, run the full suite, and test a real local two-turn chat before beginning Module 1.
- [ ] Begin Module 1: design the SQLite data boundary and migrations before storing personal data.
- [ ] Define the assistant's first tool registry and permission-enforcement path before adding any tool.
- [ ] Add a web/search tool only behind the tool registry and approval layer.
- [ ] Add a bounded, redacted local audit writer before tools or persistent
  personal-data operations are enabled.

## Session history

### 2026-08-21 01:09 MDT

Completed:

- Created the safe Git ignore rules and initial project documentation.
- Created the Python package layout, virtual environment, project metadata, smoke test, and local test workflow.
- Added and tested the permission-policy rulebook.
- Added GitHub Actions automation for tests; its first run completed successfully.
- Added `docs/revisit-later.md` for concepts to return to after the project has more working pieces.

Next:

- Build the permission-enforcement gateway and its tests.

### 2026-08-21 02:41 MDT

Completed:

- Added the authorization gateway, including tests that distinguish allowed, approval-required, and permanently denied actions.
- Added a replaceable `LanguageModel` contract and its initial local Ollama implementation.
- Installed and tested the local `qwen3:14b` model through Ollama; model files remain outside the repository.
- Configured optimized local defaults: an 8K context window, Qwen thinking output hidden, startup preload, and a five-minute idle model timeout.
- Added a minimal command-line chat interface and tests. It safely remains conversation-only: it cannot use tools, browse, read files, or access personal data.
- Pushed the implementation milestone to GitHub; the GitHub Actions workflow was triggered by that push.

Next:

- Centralize the connection and model settings so future model experiments require one small, obvious edit.
- Add bounded session-only conversation history before deciding what should become persistent SQLite memory.

### 2026-08-21 02:49 MDT

Completed:

- Updated the command-line chat interface to stream Qwen's response text as it is generated, rather than waiting silently for a complete answer.
- Kept the original non-streaming `generate()` path as the shared baseline for simple or future model adapters; streaming is an optional extension.
- Added automated streaming tests and verified one small response against the real local Ollama model.
- Optimized the initial performance defaults from an 8K context window to 4K and added a 400-token response cap; both can be changed later in `OllamaSettings`.
- Added a concise-answer instruction, a visible notice when the model reaches its cap, a 1,200-token `/long <question>` command, a 2,000-token `/max <question>` command, and a `/limit <1-2000> <question>` command for custom response budgets.

Next:

- Resume with centralized model and connection settings, then bounded session-only conversation history.

### 2026-08-21 03:21 MDT

Completed:

- Centralized non-secret model, connection, response-budget, and session-history settings in `config.py`, with validated machine-local environment overrides.
- Added bounded session-only conversation context. Recent turns remain in RAM only and are erased when the app closes.
- Added and documented response-budget commands: normal (400 tokens), `/long` (1,200), `/max` (2,000), and `/limit` (custom 1–2,000).
- Added the initial conversation policy, which remains separate from action permissions.
- Updated the README and architecture guide with current behavior and run instructions.
- Verified the complete unit suite and a real two-turn local chat: the assistant remembered `pineapple` only within that open session.

Next:

- Module 1 starts with a deliberate SQLite data boundary and migration plan, before any personal information is stored.

### 2026-08-21 03:36 MDT

Session close:

- Reviewed the Module 0 resource tradeoffs: 4K context, bounded session history, streaming, and bounded response budgets.
- Confirmed the session-memory boundary: older recent context is shortened first, and closing the app clears all session context.
- Module 0 is ready to be pushed as the completed local-chat foundation.

Next session:

- Begin Module 1 by designing the SQLite data boundary and migrations before storing any personal data.

### 2026-08-21 — Module 0 review follow-up

Completed:

- Performed a read-only security, privacy, correctness, and efficiency review of Module 0.
- Confirmed the repository was clean, the unit test suite passed, and no tracked secret, database, browser-state, log, or model files were found.
- Identified no active tool or credential exposure in the present conversation-only app, but identified hardening work required before adding SQLite data, tools, or browser workflows.

Next:

- Complete the ordered Module 0.1 hardening checklist above before Module 1.

### 2026-08-23 — Module 0.1 local connection boundary

Completed:

- Added a shared local-only HTTP boundary for Ollama generation, streaming,
  and service health checks.
- Restricted the Ollama URL to numeric IPv4 or IPv6 loopback HTTP addresses
  with an explicit port; rejected hostnames, remote addresses, credentials,
  query strings, fragments, and base paths.
- Disabled environment proxies and HTTP redirects for every production Ollama
  request.
- Added focused URL, proxy, redirect, configuration, and service tests. The
  complete suite passes with 49 tests.

Next:

- Replace character-counted session history with a token-aware RAM budget that
  includes the system instruction and current user message.
- Move conversation history to structured roles as part of the same change.

### 2026-08-23 — Shared token ceiling and audit plan

Completed:

- Enforced a 2,000-token hard ceiling in the shared model request contract and
  the Ollama adapter while retaining configurable defaults beneath it.
- Validated that a machine-local context setting can be increased independently
  to 32K tokens.
- Documented a bounded, redacted local audit-trail design for security and
  workflow diagnosis.
- Expanded the complete suite to 58 passing tests.

Design decisions:

- Keep the hard response ceiling at 2,000 tokens while allowing configurable
  defaults and per-request limits below it.
- Keep the context window independently configurable; the shared default is now
  16K and a future desktop configuration may increase it to 32K.
- Establish the bounded, redacted audit trail described in
  `docs/audit-logging.md` before enabling tool execution or personal-data
  operations.

Next:

- Replace character-counted session history with a token-aware RAM budget and
  structured conversation roles in one coordinated change.
