# Audit Logging Design

## Purpose

The assistant needs a local audit trail that can explain security decisions and
trace future agent operations without turning logs into a second store of
personal data. Logging must support diagnosis, not weaken the boundaries it
observes.

This document records the design requirement. The persistent audit writer will
be implemented before tools or personal-data operations are enabled.

## Events to record

Security and workflow boundaries should emit structured events for:

- local model connection attempts, failures, and blocked redirects;
- model request start, completion, cancellation, and safe error category;
- proposed tool actions and permission decisions;
- approval receipt issuance, verification, use, expiry, and rejection;
- tool execution start and outcome;
- database migration and repository-operation outcomes; and
- startup, shutdown, configuration validation, and audit-writer failures.

Each event should contain a UTC timestamp, event identifier, correlation
identifier, component, operation, outcome, stable reason code, duration when
useful, and carefully selected non-sensitive metadata.

## Data that must not be logged by default

- prompts, model responses, or conversation history;
- personal records or database query results;
- credentials, cookies, tokens, or approval secrets;
- complete URLs containing credentials, query strings, or fragments;
- raw untrusted text that could inject control characters or forged log lines;
  or
- full tool arguments unless a field has an explicit safe logging policy.

For a blocked redirect, record that a redirect was refused, its HTTP status,
and a sanitized destination classification. Never follow it for logging and do
not preserve a potentially sensitive raw location.

## Storage and safety requirements

- Logs remain local and excluded from Git.
- Use a structured format with control-character sanitization.
- Apply restrictive file permissions, bounded size, rotation, and a defined
  retention period.
- Logging failure must never turn a denial into an allowance or disable a safety
  boundary. Operations designated as audit-required fail closed before they
  execute when their minimum event cannot be recorded. Emergency lock, safe
  shutdown, and other containment paths must remain available and surface a
  trusted local warning when normal logging is unavailable.
- Correlation identifiers should connect a user request, model request,
  permission decision, approval receipt, tool execution, and result.
- Diagnostic verbosity should be configurable, while minimum security events
  remain available.

## Implementation sequence

1. Define typed audit events and stable reason codes alongside Module 0.1
   security boundaries.
2. Add a replaceable audit sink with a no-content, in-memory test sink.
3. Add the bounded local writer before enabling tools or persistent personal
   data operations.
4. Test redaction, log-injection resistance, rotation, retention, and behavior
   when the writer fails.
