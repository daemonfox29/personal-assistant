# Audit Logging Design

## Purpose

The assistant needs a local audit trail that can explain security decisions and
trace future agent operations without turning logs into a second store of
personal data. Logging must support diagnosis, not weaken the boundaries it
observes.

The foundational typed event contract and bounded local writer are implemented.
Each future tool and personal-data operation must integrate its own events and
focused redaction tests before that capability is enabled.

## Events to record

Security and workflow boundaries should emit structured events for:

- local model connection attempts, failures, and blocked redirects;
- model request start, completion, cancellation, and safe error category;
- proposed tool actions and permission decisions;
- approval receipt issuance, verification, use, expiry, and rejection;
- tool execution start and outcome;
- automatic-unlock credential reads, verified enrollment, deletion, and safe
  fallback without the credential value or account/path identifiers;
- bounded runtime-preference update attempts and outcomes, including only the
  non-secret numeric context and response limits;
- database migration and repository-operation outcomes; and
- startup, shutdown, configuration validation or update, and audit-writer
  failures.

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

- [x] Define typed audit events and stable reason codes.
- [x] Add a replaceable audit-sink protocol and a content-minimizing in-memory
  test sink.
- [x] Add an explicitly located JSON Lines writer with a 16 KiB event ceiling,
  1 MiB active-file ceiling, five retained rotations, `0600` file permissions,
  and `0700` permissions for a newly created audit directory on POSIX systems.
- [x] Test schema bounds, log-injection resistance, file permissions, event and
  file ceilings, rotation, retention, symbolic-link refusal, and safe writer
  failures.
- [ ] Integrate typed events into each model, authorization, tool, database, and
  backup boundary as that boundary is implemented or deliberately revised.

The encrypted-database connection and native automatic-unlock credential
boundaries now emit start, success, and safe failure events. Repository queries,
migrations, backups, model requests, authorization decisions, and tools retain
their own focused integration requirements as those paths evolve.

The writer accepts only typed enums, UUIDs, bounded integers, and allowlisted
safe labels. It has no free-form message field. This makes prompt, response,
credential, URL, path, exception-text, and personal-record logging unavailable
through the normal event contract rather than relying only on later redaction.
