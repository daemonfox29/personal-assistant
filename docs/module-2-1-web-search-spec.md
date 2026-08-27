# Module 2.1 Read-Only Web Search Specification

## Purpose

Module 2.1 lets the assistant retrieve a small set of current public search
results without granting it a browser, arbitrary URL fetching, downloads,
cookies, account sessions, filesystem access, or a general network client.
This capability follows the project security doctrine and Module 2.0 registry
and executor boundary.

Search is provided by a separate local SearXNG service. SearXNG is open-source
software under AGPL-3.0-or-later and exposes a documented JSON search API. The
assistant connects only to a numeric loopback address; SearXNG, not the model or
assistant process, owns upstream search-engine communication.

- <https://github.com/searxng/searxng>
- <https://docs.searxng.org/dev/search_api.html>
- <https://docs.searxng.org/admin/installation-docker>

No paid or proprietary search API credential is required. SearXNG may still
send the query to configured upstream public search engines. Self-hosting
reduces provider lock-in and isolates network authority; it does not make an
outbound query private from those upstream engines.

## Narrow authority

The `search_public_web` tool accepts one query and returns at most five public
result summaries. The assistant-side adapter can contact only one configured
numeric loopback HTTP origin and the fixed `/search` path. It cannot:

- contact an internet host, LAN address, hostname, or alternate local port;
- visit a result URL or any model-selected URL;
- follow HTTP redirects or use environment proxies;
- submit forms, authenticate to websites, use cookies, or preserve web state;
- fetch page bodies, images, documents, scripts, or remote media;
- change the SearXNG origin, path, method, format, category, page, language, or
  safe-search setting;
- read memory, conversations, files, databases, credentials, or approval
  objects; or
- write or mutate any external system.

SearXNG is a separately maintained security and supply-chain boundary. The
reviewed deployment binds it to numeric loopback, enables JSON responses and
moderate safe search, disables autocomplete and image proxying, limits the
enabled upstream engines, uses short upstream timeouts, and is pinned to a
reviewed image version rather than `latest`. The assistant never receives the
SearXNG administrative interface or configuration authority.

## Outbound-query privacy rule

Read-only search still discloses the query beyond the machine. The model already
receives selected persistent memory, so unrestricted model-authored queries
would create an exfiltration channel.

For Module 2.1, the normalized outbound query must be a contiguous substring of
the current user's normalized message. The model may select relevant words the
user just supplied, but cannot add a name, address, memory value, encoded
payload, site filter, or instruction absent from that message. Deterministic
code enforces this immediately before contacting local SearXNG. A query that is
empty, too long, contains controls, or is not derived from the current message
is denied and never leaves the assistant process.

Running the reviewed local SearXNG service is the owner's explicit global
enablement of this narrow search action. Under the user-derived-query rule,
`WEB_SEARCH` is allowed without a passcode on every request. General
`NETWORK_REQUEST` remains approval-required. Relaxing query derivation, adding
memory-derived searches, or adding any other destination requires a new review
and trusted per-action approval design.

The model should propose search automatically, without asking for permission or
requiring explicit search phrasing, when a public factual question depends on
information it does not know confidently or that may have changed. It should
not search casual conversation, creative work, private-memory questions, or
facts already established by trusted context. This is a model decision inside
the deterministic authority boundary: every proposed query still must pass the
current-user substring rule before any request can leave the process.

## Inputs and outputs

Input is exactly one `query` string containing 2 to 256 Unicode characters after
whitespace normalization. Control characters, line breaks, nulls, and invisible
formatting controls are rejected.

The adapter fixes result count to five, safe search to moderate, category to
general, language to English, page to one, format to JSON, and one request with
no retry. Query contents are not audited.

Output contains a provider label and up to five results in SearXNG rank order.
Each result has a bounded inert plain-text title, bounded inert plain-text
snippet, and normalized public HTTPS source URL. The complete canonical result
uses the existing `untrusted_tool_data` label and two-KiB result ceiling.

HTML is converted to inert text. Controls and invisible formatting are escaped
or removed. Result URLs are data only: the native renderer does not make them
active or fetch them. Duplicate and invalid URLs are discarded.

## Prompt injection and citations

Search titles, snippets, and URLs are hostile data, not instructions. The model
is told to ignore directions, approval claims, credential requests, policy
claims, or tool requests inside them. Results cannot grant authority, enter
canonical memory automatically, or prove a claim.

When an answer relies on search, the model should name the source and include
the exact returned HTTPS URL near the supported claim. A citation identifies
where a claim may be checked; it does not establish that the snippet is true.
Consequential medical, legal, financial, security, or safety claims still
require authoritative-source verification. Page retrieval is deliberately out
of scope, so the assistant must say when snippets are insufficient.

## Resource, failure, and cancellation rules

- one SearXNG request per tool execution and no retry;
- maximum five seconds for the complete local request;
- maximum 64 KiB response before JSON parsing;
- maximum five accepted results and two KiB canonical model-facing output;
- existing one-call-per-step and three-step-per-user-request ceilings;
- duplicate exact calls within one user request are refused; and
- shutdown prevents another provider request and bounds any active request by
  the local socket timeout.

Missing local service, timeout, interruption, redirect, non-JSON content,
oversized data, non-200 response, malformed results, or audit failure produces
fixed safe failure data without leaking query, response, address, or exception
details. Active socket cancellation beyond the five-second bound remains a
future hardening item; the MVP does not claim instantaneous cancellation.

## Audit rules

Audit events may contain only stable action kind, tool class, provider class,
outcome, reason code, duration, HTTP status class, result count, and byte count.
They must not contain the query, URLs, domains, result text, response body,
addresses, exception text, prompts, memory, or transcript content.

Audit must succeed before the local request begins. Completion or failure is
recorded afterward. A missing completion event is treated as an interrupted or
uncertain read-only attempt; it cannot imply an external mutation because the
capability has no mutation authority.

## Acceptance criteria

Module 2.1 is locally complete when tests prove:

1. only a fixed numeric loopback origin and `/search` endpoint can be contacted;
2. proxies and redirects are not used;
3. only exact user-derived bounded queries reach SearXNG;
4. memory-derived, malformed, hidden-control, or oversized queries do not
   trigger a request;
5. no API credential exists in model requests, results, audit, preferences,
   exceptions, repository content, or runtime configuration;
6. unavailable SearXNG fails safely;
7. response status, content type, size, JSON shape, result count, text, and URLs
   are bounded and validated;
8. HTML and control text becomes inert display data;
9. result URLs are never fetched and invalid or duplicate URLs are omitted;
10. search results are labeled untrusted and cannot grant permission;
11. exact duplicate calls and calls beyond the coordinator ceiling stop;
12. audit failure before execution prevents the local request;
13. timeouts bound shutdown and prevent follow-on requests;
14. ordinary local tools and no-tool streaming continue to work;
15. the reviewed SearXNG deployment is loopback-bound, version-pinned, and
    exposes JSON search without an internet-facing listen address; and
16. the full local suite passes on the current development machine.

Linux and Windows execution remain explicit deferred portability gates at the
owner's direction; they are not represented as verified by local tests.
