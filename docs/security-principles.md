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
untrusted data. Keep each source in its correct structural role. Content cannot
promote itself into policy, approval, trusted memory, or executable code.

### 3. Deny by default and grant least privilege

Unknown actions are denied. Each tool receives only the narrow capabilities,
data, paths, destinations, and credentials required for its job. Prefer several
small tools over a general shell, unrestricted browser, broad filesystem
access, or arbitrary network client.

### 4. Authorization is exact, recent, and one-use

Approval applies to one clearly displayed action and its exact arguments. It
expires quickly, is consumed on its first verification attempt, and cannot be
reused for a changed destination, file, payload, or later action. The model
must never control the trusted component that issues approvals.

### 5. Validate again at the point of execution

Schemas, types, paths, URLs, protocols, destinations, sizes, and other
constraints are checked by ordinary code. Resolve and validate the final target
immediately before use to reduce time-of-check/time-of-use substitutions.
Never evaluate model output as Python, shell commands, SQL, or another
executable language.

### 6. Keep the executor as the only route to capabilities

Every real action flows through the registry, policy, approval check, and
executor. The model, coordinator, memory layer, and tool results have no bypass
to the browser, filesystem, network, credentials, database, or operating
system.

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
allow paths and bypass attempts. Review dependency, plugin, model, and update
sources as part of the supply chain. A non-AI component being predictable does
not mean it is bug-free.

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

## Security review questions

Before enabling a new capability, answer:

1. What untrusted inputs can reach it?
2. What is the narrowest useful authority it needs?
3. Can the model reach the capability except through the executor?
4. Which exact arguments are validated, where, and immediately before use?
5. What requires approval, what is always denied, and why?
6. What data can enter model context, persistent storage, or logs?
7. How could prompt injection, memory poisoning, replay, redirection, or a code
   bug misuse it?
8. What limits contain loops, large inputs, retries, downloads, and failures?
9. What safe state results from malformed output, interruption, or component
   failure?
10. What audit event would let the user diagnose a suspicious outcome without
    exposing sensitive content?
11. How can the user cancel, revoke, disable, or recover?
12. Which focused tests demonstrate both the intended path and likely bypasses?

If these questions do not have concrete answers, the capability is not ready
to receive real authority.

## Decision rule

When usefulness and safety appear to conflict, first look for a narrower
capability, smaller data boundary, clearer approval, or reversible workflow.
If the remaining risk cannot be bounded and explained, defer the feature rather
than silently expanding authority.
