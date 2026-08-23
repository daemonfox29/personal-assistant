# Security Principles

## Purpose

This document is the project's security doctrine. Use it when designing,
reviewing, or approving every model, memory, tool, browser, data, interface,
plugin, and audit feature. Convenience does not silently override these
principles. Record and justify any deliberate exception.

## Foundational belief

The model is the primary intelligent wildcard, but it is not the only possible
source of harm. Assume that the model can be confused, manipulated, or wrong;
external content can be hostile; deterministic code can contain bugs; and
isolation mechanisms can fail.

Security therefore comes from overlapping, independently enforced boundaries.
No single model instruction, approval prompt, validator, sandbox, or test is
sufficient by itself.

## Operating assumptions

### 1. The model proposes; deterministic code disposes

The model may interpret requests, reason, and propose structured actions. It
does not grant permissions, issue approval receipts, select its own authority,
or call operating-system capabilities directly. Only deterministic code may
validate, authorize, and execute a registered action.

Model statements are not evidence that approval occurred, a tool ran, data was
saved, or an external system returned a particular result. Trusted program
state and verified tool results establish those facts.

### 2. All external and generated content is untrusted

Treat user input, webpages, emails, documents, attachments, API responses,
retrieved records, tool results, model output, and other agents' output as
untrusted data. Keep each source in its correct structural role, but do not
mistake role separation for a security boundary inside the model: the model may
still follow instructions found in untrusted content. Deterministic code must
ensure that content cannot become policy, approval, trusted memory, or
executable authority even when the model treats it as an instruction.

### 3. Deny by default and grant least privilege

Unknown actions are denied. Each tool receives only the narrow capabilities,
data, paths, destinations, and credentials required for its job. Prefer several
small tools over a general shell, unrestricted browser, broad filesystem
access, or arbitrary network client.

Review combined capabilities, not only individual ones. Any component that can
simultaneously ingest untrusted content, access sensitive data, and communicate
externally or change state has a high exfiltration and confused-deputy risk.
Remove at least one capability where practical; otherwise require narrow
per-action approval, explicit data previews, and documented residual risk.

### 4. Authorization is exact, recent, and one-use

Approval applies to one clearly displayed action and its exact arguments. It
expires quickly, is consumed on its first verification attempt, and cannot be
reused for a changed destination, file, payload, or later action. The model
must never control the trusted component that issues approvals.

Future multi-interface or multi-user receipts must also bind the approving
identity, trusted interface, and session. One session cannot spend another
session's approval.

### 5. Validate again at the point of execution

Schemas, types, paths, URLs, protocols, destinations, sizes, and other
constraints are checked by ordinary code. Resolve and validate the final target
immediately before use to reduce time-of-check/time-of-use substitutions.
Never evaluate model output as Python, shell commands, SQL, or another
executable language.

Escape and sanitize model output before displaying or passing it downstream.
Rendering must not automatically fetch remote images, follow links, interpret
HTML, execute terminal controls, or expose hidden Unicode channels. Displayed
actions must match the exact normalized arguments the executor will receive.

### 6. Keep the executor as the only route to capabilities

Every real action flows through the registry, policy, approval check, and
executor. The model, coordinator, memory layer, and tool results have no bypass
to the browser, filesystem, network, credentials, database, or operating
system.

Agents cannot delegate, inherit, or transfer authority implicitly. Each worker
receives its own narrow task, capability set, data boundary, and resource
budget. An agent's claim that approval occurred is not evidence, and an
approval receipt or credential issued for one actor is not reusable by another.

### 7. Keep secrets outside model context

Passwords, private keys, session cookies, access tokens, and approval tokens
must not enter prompts, conversation memory, normal tool results, or logs.
Future credential helpers should use secrets on behalf of a narrowly scoped
tool without revealing their values to the model.

### 8. Minimize data exposure and retention

Give the model and each tool only the fields and content needed for the current
task. Bound context, RAM history, downloads, tool results, logs, and persistent
records. Redact sensitive values and separate generated summaries from
canonical personal data.

### 9. Persistent memory has provenance and cannot grant authority

Stored information records where it came from and whether it was user-entered,
imported, tool-observed, or model-generated. Retrieved text remains data. No
memory entry can permanently grant permission, weaken policy, or prove that a
past or future action is approved.

### 10. Sandboxes reduce risk; they do not erase it

Use separate browser profiles, restricted processes, OS permissions, network
limits, and isolated storage where practical. Continue enforcing narrow tools,
validation, authorization, and data minimization even inside a sandbox.

### 11. Deterministic components are fallible too

Fail closed on malformed, missing, interrupted, or unexpected states. Test
allow paths and bypass attempts. Pin and verify dependencies, models, plugins,
MCP servers, and tool packages where practical; inspect tool descriptions and
remove unused capabilities. Re-run the security review after changes to a
model, prompt, policy, dependency, tool, interface, or configuration. Test as
though an attacker knows the defenses rather than relying on secrecy or static
attack examples. A non-AI component being predictable does not mean it is
bug-free.

### 12. Bound cost, time, and repetition

Limit tool calls, redirects, retries, task depth, execution time, downloaded
bytes, context growth, memory growth, and approval prompts. Detect loops and
provide cancellation. Resource exhaustion and approval fatigue are security
problems, not merely performance problems.

### 13. Audit decisions without creating a second data leak

Record enough sanitized metadata to reconstruct what was proposed, allowed,
approved, denied, attempted, and completed. Do not routinely record prompt
contents, personal documents, credentials, cookies, receipt tokens, or other
secrets. Bound retention and make security-relevant events correlatable.

### 14. The user retains meaningful control

Before consequential actions, show the exact target, data involved, important
effects, and whether the action is reversible. Provide reliable cancellation,
receipt revocation, tool disablement, session shutdown, and recent-action
inspection. Avoid vague or repetitive approval dialogs.

### 15. Verify claims in proportion to their consequences

Do not treat fluent model output as fact. Preserve source provenance,
distinguish tool observations from model inference, and verify consequential
claims with authoritative sources or deterministic checks before they drive an
action or persistent record. Require stronger evidence as potential harm grows.

### 16. Plan for containment and recovery

Assume a boundary may eventually fail. Provide a way to disable tools and
external connections, revoke approvals, rotate affected credentials, preserve
sanitized evidence, identify poisoned memory, restore known-good state, and
review the incident before authority is re-enabled.

## Security review questions

Before enabling a new capability, answer:

1. What untrusted inputs can reach it?
2. What is the narrowest useful authority it needs?
3. Can the model reach the capability except through the executor?
4. Does it combine untrusted input, sensitive data, and external communication
   or state change? Which capability can be removed or isolated?
5. Which exact arguments are validated, where, and immediately before use?
6. What requires approval, what is always denied, and which identity, interface,
   and session own that decision?
7. What data can enter model context, tool output, persistent storage, or logs?
8. How could prompt injection, memory poisoning, replay, redirection, or a code
   bug misuse it?
9. Can rendering model or tool output trigger network requests, hide content,
   execute controls, or misrepresent the action being approved?
10. Can an agent delegate, inherit, or transfer authority, credentials, data, or
    approval beyond its assigned boundary?
11. What limits contain loops, large inputs, retries, downloads, and failures?
12. What safe state results from malformed output, interruption, or component
   failure?
13. What audit event would let the user diagnose a suspicious outcome without
    exposing sensitive content?
14. How can the user cancel, revoke, contain, restore, and safely re-enable it?
15. Which dependencies, models, plugins, tools, and configurations form its
    supply chain, and how are changes verified?
16. Which consequential claims require authoritative or deterministic
    verification before use?
17. Which focused and adaptive tests demonstrate the intended path and likely
    bypasses when the attacker knows the defenses?

If these questions do not have concrete answers, the capability is not ready
to receive real authority.

## Decision rule

When usefulness and safety appear to conflict, first look for a narrower
capability, smaller data boundary, clearer approval, or reversible workflow.
If the remaining risk cannot be bounded and explained, defer the feature rather
than silently expanding authority.

## Reference guidance

Review this doctrine periodically against the current
[OWASP GenAI LLM Top 10](https://genai.owasp.org/initiatives/top-10-for-llm-and-genai/)
and the
[NIST Generative AI Profile](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence).
External frameworks inform this project, but the deterministic boundaries and
local-first constraints above remain enforceable project requirements.
