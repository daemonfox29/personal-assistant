# Project Status

This document is the handoff point between coding sessions. At the end of each session, update the current status, outstanding actions, and session history below.

## Current status

- Module 0 and the Module 0.1 hardening gate are complete: Git safety rules,
  project documentation, source layout, virtual environment, project metadata,
  deterministic security boundaries, a local model adapter, and a runnable chat
  are in place. The Module 1 persistent-memory specification is approved;
  implementation has not begun.
- The local permission policy is implemented and covered by automated tests.
- GitHub Actions is configured to test pull requests targeting `main` before
  merge. The public repository has an active ruleset requiring the `test`
  check and blocking force pushes and deletion. Non-draft pull requests from
  the repository owner's own branches automatically enable squash auto-merge.
  Post-merge runs are intentionally deferred to conserve Actions usage.
- Runtime personal data, browser state, secrets, logs, databases, and model files remain excluded from Git.
- The assistant has a replaceable language-model interface and a local Ollama adapter configured for `qwen3:14b`.
- Starting the command-line assistant starts Ollama if needed, uses Ollama's
  empty-request preload without evaluating a chat prompt, uses a 16K context
  window for real chats, caps normal responses at 400 tokens, and asks Ollama
  to unload the model after five idle minutes.
- Shared defaults and machine-local environment overrides are centralized in `config.py`.
- The local-only chat streams responses and has session-only conversation memory while it is open. It has no persistent memory, tools, browser access, personal-data access, credential access, or web capability.
- Conversation policy is documented separately from the action-permission policy.
- `docs/security-principles.md` is the governing threat model and review
  checklist for every future capability; design decisions should explicitly
  follow it rather than relying on model behavior for safety.
- The Ollama adapter and service health check now accept only explicit numeric
  loopback HTTP addresses, ignore environment proxies, and refuse redirects.
- The shared model request contract enforces a 2,000-token response ceiling;
  normal, long, and machine-local defaults remain configurable beneath it.
- Session memory retains only complete recent turns within a conservative RAM
  token budget. Model requests use separate system, user, and assistant roles,
  reserve response space, and reject a current message that cannot fit.
- Approval-required actions use opaque receipts bound to the exact action and
  canonical arguments. Receipts are consumed on first use and expire within a
  short hard-limited lifetime.
- Terminal output escapes control and invisible formatting characters. Expected
  local-model, malformed-response, configuration, and interruption failures
  fail closed with fixed user-safe messages.

## Outstanding actions

Work through these in order unless project needs change. Module 1 must wait until the Module 0.1 hardening work below is complete.

- [x] Module 0.1: enforce a truly local-only Ollama connection. Accept only an explicit loopback HTTP address, and prevent proxy use and HTTP redirects. Keep a future remote-model adapter separate and opt-in.
- [x] Module 0.1: make session memory genuinely bounded in RAM, using a token-aware budget that includes the system instruction and current user message. Define predictable handling for one message that is too large.
- [x] Module 0.1: replace the temporary `user_approved=True` switch with a one-use, short-lived approval receipt tied to the exact requested action and arguments. Only a trusted interface may issue it; the executor must verify it.
- [x] Module 0.1: enforce the 2,000-token response ceiling in the shared model adapter, not only in the command-line chat interface.
- [x] Module 0.1: move conversation history to structured `system`, `user`, and `assistant` messages before adding tools, so user text cannot impersonate another role.
- [x] Module 0.1: sanitize control characters from model output before printing it to the terminal. Add friendly error handling for unavailable Ollama, missing models, malformed responses, and interrupted startup.
- [x] Module 0.1: make warm-up lightweight, improve documentation wording about privacy and in-memory clearing, extend secret-file ignore rules, and harden the GitHub Actions workflow (full action SHA pins and least-privilege checkout settings).
- [x] Module 0.1: add focused tests for every hardening rule, run the full suite, and test a real local two-turn chat before beginning Module 1.
- [x] Begin Module 1: design the encrypted SQLite data boundary, memory
  lifecycle, retrieval rules, migrations, backup, and acceptance tests before
  storing personal data.
- [ ] Module 1 prerequisite: implement the bounded, redacted audit writer before
  persistent personal-data operations are enabled.
- [ ] Module 1: verify and select a cross-platform encrypted SQLite provider and
  key-provider boundary using synthetic data.
- [ ] Module 1: implement and test checksummed migrations, typed repositories,
  bounded retrieval, memory suggestions, and encrypted backup/restore in the
  order defined by `docs/module-1-memory-spec.md`.
- [ ] Define the assistant's first tool registry and permission-enforcement path before adding any tool.
- [ ] Add a web/search tool only behind the tool registry and approval layer.

## Session history

### 2026-08-24 — Module 1 persistent-memory specification

Completed:

- Defined the encrypted, cross-platform SQLite boundary and forward-only
  checksummed migration contract.
- Specified typed records, append-only revisions, entities, profiles,
  provenance, scopes, sensitivity, mention rules, contradictions, evidence-
  linked insights, candidate memory suggestions, and deletion behavior.
- Defined bounded indexed retrieval, measurable performance targets, retrieval
  receipts, daily encrypted external-drive backup, verified restore, and
  non-destructive future maintenance.
- Defined passcode-backed high-risk authorization without a separate login for
  ordinary conversation, while keeping foundational guardrails unavailable to
  conversational override.
- Added focused acceptance criteria and an ordered implementation plan. No
  database or personal-data persistence code was added.

Next:

- Implement the bounded redacted audit writer required before personal-data
  operations.
- Spike the encrypted SQLite and key-provider boundary using synthetic data.

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

### 2026-08-23 — Structured, token-bounded session memory

Completed:

- Replaced flattened prompt strings with explicit system, user, and assistant
  messages sent through Ollama's chat endpoint.
- Bounded stored RAM history using complete-turn eviction and a conservative
  token estimate that reserves room for the current request and response.
- Added predictable rejection for a current message that cannot fit instead of
  silently truncating it or sending an oversized request.
- Added focused role, RAM-budget, request-budget, oversized-message, adapter,
  and chat tests. The complete suite passes with 65 tests.
- Verified a real two-turn local Qwen chat retained the session code
  `cobalt-731` through the structured message path.

Next:

- Replace the temporary boolean approval switch with a one-use, short-lived
  receipt tied to the exact action and arguments.

### 2026-08-23 — Exact, one-use approval receipts

Completed:

- Replaced the forgeable `user_approved=True` input with opaque receipts held
  by an in-process approval authority.
- Bound each receipt to one action and a canonical digest of its exact
  arguments, with stable handling for reordered mapping keys.
- Made every verification attempt consume the receipt, whether it succeeds or
  fails, and enforced a 60-second default lifetime with a five-minute ceiling.
- Rejected forged, expired, reused, mismatched, and malformed approvals in
  focused tests. The complete suite passes with 75 tests.
- Removed expired unused records during authority activity so the receipt
  registry does not grow indefinitely.

Next:

- Sanitize terminal control characters and add friendly model/startup error
  handling.

### 2026-08-23 — Safe terminal output and model failures

Completed:

- Added one terminal-output boundary that preserves readable newlines and tabs
  while escaping executable controls and invisible Unicode formatting channels.
- Applied sanitization to both complete and streaming model responses before
  display or reuse as session history.
- Added typed model-boundary failures for unavailable Ollama, missing models,
  malformed responses, and failed requests without surfacing raw service text.
- Made startup, active chat, end-of-input, and keyboard interruption paths fail
  with clear fixed messages and no traceback for expected failures.
- Expanded focused malformed-response, control-character, invisible-Unicode,
  service-launch, friendly-error, and interruption coverage. The complete suite
  passes with 89 tests.

Next:

- Make model warm-up lightweight, tighten privacy/clearing documentation and
  secret ignores, and finish GitHub Actions hardening.

### 2026-08-23 — Lightweight preload and repository hardening

Completed:

- Replaced the empty user-message warm-up with Ollama's documented empty API
  preload, avoiding chat prompt evaluation and 16K generation options at startup.
- Clarified that closing the app drops application references and prevents
  deliberate persistence, but does not promise physical erasure from Python,
  Ollama, macOS, swap, backups, or crash diagnostics.
- Expanded ignore coverage for credential exports, key containers, tokens,
  cookie exports, password databases, SSH keys, and local secret directories.
- Confirmed reusable workflow actions are immutable SHA pins and checkout uses
  read-only permissions without persisted credentials; made shallow/no-LFS/
  no-submodule behavior explicit, bounded auto-merge time, and cancelled stale
  pull-request runs to conserve Actions usage.
- Added repository-safety regression tests for secret ignores, immutable action
  pins, and checkout credentials. The complete suite passes with 92 tests.

Next:

- Complete the final Module 0.1 verification gate, including a real local
  two-turn chat, before beginning Module 1 persistence design.

### 2026-08-23 — Module 0.1 final verification gate

Gate result: **Passed with no blocking findings.**

Evidence:

- Ran all 92 automated tests, including authorization replay/mismatch/expiry,
  local-only networking, structured roles, bounded session memory, terminal
  sanitization, malformed model responses, secret ignores, and workflow pins.
- Confirmed the installed Python environment has no broken requirements and the
  Git object database passes its integrity check.
- Confirmed no tracked filenames match the protected secret/credential patterns
  and no tracked source contains the scanned private-key or common-token
  signatures.
- Reviewed execution and network primitives: there is no general `eval`, `exec`,
  shell execution, or unrestricted HTTP client. The only process launch is the
  fixed macOS Ollama launcher, and model HTTP remains behind the validated
  loopback-only opener.
- Ran the real application with local `qwen3:14b` through startup, empty preload,
  structured streaming, session memory, terminal rendering, and clean shutdown.
  It remembered and returned the two-turn session code `amber-927` exactly.
- Rechecked the implemented boundaries against `docs/security-principles.md`.
  Module 0.1 grants no browser, tool, persistent-memory, credential, or remote
  model capability, so those future surfaces remain closed by default.

Decision:

- Module 0.1 is complete. Begin Module 1 with persistence boundary and migration
  design before writing personal data.

### 2026-08-23 — Security doctrine

Completed:

- Established a first-class security doctrine covering hostile inputs,
  model fallibility, least privilege, exact authorization, executor isolation,
  secret handling, data minimization, memory provenance, sandbox limits,
  deterministic-code bugs, resource bounds, audit safety, and user control.
- Added a twelve-question security review that every new capability must pass
  before receiving real authority.
- Linked the doctrine from the documentation index, architecture, development
  workflow, and main README so it remains part of future decisions.

Next:

- Sanitize terminal control characters and add friendly model/startup error
  handling.

### 2026-08-23 — Security doctrine review

Completed:

- Rechecked the doctrine against current OWASP GenAI and NIST guidance.
- Clarified that structured roles do not create a model-enforced trust boundary;
  deterministic code must contain successful prompt injection.
- Added explicit rules for dangerous capability combinations, safe output
  rendering, agent authority isolation, identity/session-bound approvals,
  factual verification, supply-chain change review, adaptive testing, and
  incident containment and recovery.
- Expanded the reusable capability review from twelve to seventeen questions
  and recorded the external guidance used for periodic reassessment.

Next:

- Sanitize terminal control characters and add friendly model/startup error
  handling.
