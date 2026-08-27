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
recovery or operating-system-assisted unlock:

Native widgets or recovery CLI → narrow application/conversation service →
bounded encrypted retrieval → untrusted-data system envelope → token-bounded
structured messages → model adapter → local Ollama model → sanitized streamed
display events

After encrypted unlock, the application service may also append structured
conversation messages and return bounded sidebar summaries. Those transcript
tables are not canonical memory and are not searched by ordinary memory
retrieval. Selecting one conversation restores only its newest complete turns
through the existing token-bounded RAM context.

For new chat-derived memory, the provenance `source_ref` contains the opaque
saved user-message ID, not its content. The trusted application service can
resolve that ID to one live conversation and exact sequence for source
navigation; widgets receive only an immutable conversation plus the sequence to
highlight. Conversation deletion cascades the source message and intentionally
leaves a dangling non-secret provenance reference, producing a fixed unavailable
outcome. Older/imported memories without this reference are never matched back
to transcripts by text. The Settings memory table similarly receives bounded
immutable inventory rows and invokes narrow source/delete methods rather than
repository handles.

The native app can retrieve the previously verified recovery secret through a
narrow operating-system credential-store adapter. The adapter is bound to the
configured data location, accepts only reviewed protected backends, and falls
back to trusted recovery entry when unavailable or stale. On macOS, the native
adapter first requires device-owner authentication through Apple Local
Authentication, allowing Touch ID or the Mac login password, and only then asks
Keychain for the stored recovery passphrase. The same macOS policy may accept a
paired Apple Watch when enabled. In the unsigned development build
this is an application-enforced sequence; a signed packaged build must move the
user-presence rule onto the Keychain item itself. The default command-line
startup remains the explicit recovery path. Both supply the memory
adapter only when a safe portable manifest and existing encrypted database
unlock successfully. A new or disabled installation follows the Module 0
session-only path. Explicit remember instructions are intercepted before model
submission. A deterministic phrase gate selects reviewed clear durable-looking
first-person statements before the main model request; an eligible exact
low-risk sentence commits synchronously without a model-analysis dependency and
produces a fixed, generic-topic UI receipt. Uncertain, contradictory, inferred,
or higher-risk
material cannot use that promotion path and produces an immediate fixed review
or clarification receipt. Other completed turns use a bounded post-response
worker for tentative suggestions. Deterministic code
may promote only a complete low-risk declarative sentence found exactly in the
user's current message and stores that sentence with trusted-interface
provenance. A model-selected exact fragment or an unambiguous lexical paraphrase
may locate the sentence but cannot author its persisted content. Ambiguous
matches, inferences, sensitive material, and conflicts enter only the
quarantined candidate inbox until trusted review confirms them. Replacing active
chat history sets a one-request handoff barrier so the next persistent-memory
request waits boundedly for preceding accepted analysis before retrieval. A
referential first request may reuse only the immediately preceding accepted user
statement as a search hint; it is not inserted as a new model role. Retrieval
shares small deterministic singular/plural normalization across memory,
transcript recall, and evidence binding. Direct owner recall may also expand a
small reviewed topic table; ordinary prompts do not receive that wider fallback.
Every returned confirmed entry includes a trusted repository `updated_at`
timestamp. When retrieved values conflict, the later update is canonical and
overrides stale details restored from an older conversation transcript. The
model never invents search terms, timestamps, or UI save receipts.
Eligible low-risk insight candidates form a separate observation layer. They
remain expiring candidates but may be retrieved into a labeled
`tentative_observations` JSON array after confirmed records have received bounded
capacity. The system contract treats each as a plausible, potentially
situational interpretation: it may qualify or challenge a confirmed default,
but cannot replace it, grant authority, authorize action, or diagnose. Only a
trusted explicit reconciliation may turn it into a global revision, a
time-bounded successor, or a scoped exception; that owner-control workflow must
retain the prior revision and is not delegated to the chat model.
Confirmed personal records receive standing owner approval for relevant ordinary
retrieval; direct-only, never-mention, restricted, and unconfirmed records do
not. Natural explicit prior-discussion language triggers bounded transcript
search immediately rather than asking whether to search.

Current Module 2.0 action flow:

User request → coordinator advertises code-owned schemas → model proposes a
structured call → registry resolves the exact name → validator bounds arguments
→ permission layer evaluates the registered action → audit records the start →
executor invokes only the registered callable → bounded untrusted tool result →
model produces the user-facing response

The model never receives a callable, audit sink, approval authority, credential,
or general execution primitive. The initial registry contains current local
date/time and bounded decimal arithmetic. Module 2.1 optionally adds a read-only
`search_public_web` entry that can contact only a configured numeric-loopback
SearXNG service. SearXNG is a separate open-source process with upstream network
authority but no model, memory, database, credential, browser, or assistant-
process access. A deterministic Colima lifecycle starts its dedicated one-GiB
profile on first use and stops it after 120 idle seconds or app shutdown. Only
the reviewed configuration directory is mounted read-only; the model cannot
control service lifecycle or configuration. The model supplies no search query;
deterministic code uses only the normalized current user message. Returned
titles, snippets, and HTTPS URLs are bounded untrusted data. The search adapter
does not fetch results; Module 2.2 owns the separate reading boundary. Calls are serial, request-
scoped, and limited to three tool steps. Browser, file, credential, shell,
arbitrary URL fetch, and arbitrary-code capabilities remain disabled.

Module 2.2 adds a distinct bounded public-page reader, not arbitrary URL fetch.
Only result numbers from the current correlated search can resolve to URLs.
DNS must contain exclusively global addresses; the socket is pinned to one
validated address while TLS remains verified for the original hostname. The
reader rejects redirects, proxies, cookies, authentication, compressed or
non-text responses, and returns only bounded inert text labeled untrusted.

## Initial scope

The first native interface uses PySide6 widgets over a narrow application
service. Widgets do not receive database connections, keys, approval authorities,
audit sinks, or model adapters. The terminal interface remains a recovery and
developer fallback over the same conversation service. The native interface can
archive structured messages in the encrypted database, while only complete
recent turns from the active conversation enter RAM context. System, user, and
assistant messages remain separate data structures and retain a conservative
token budget.

The settings widget similarly receives only bounded non-secret preference
values. It asks the application factory to atomically persist a versioned JSON
document and emit typed configuration events; it never receives the audit sink,
model adapter, database, or credential store. Context and response-limit changes
take effect when the next session is composed. Code-owned system/light/dark
palettes and an installed font preference cannot contain arbitrary stylesheet
content.

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

Closing the process drops the active RAM-context references. Module 1.5 can also
retain full structured transcripts in dedicated encrypted tables. These rows are
separate from selected memory and are loaded when the owner opens that
conversation. An explicit owner request to recall an earlier discussion can
search an encrypted FTS transcript index and inject a small neighborhood from at
most three other chats as a clearly labeled untrusted-data envelope. Ordinary
prompts do not search transcripts, the active conversation is excluded, and
Private Chat bypasses transcript storage, transcript recall, persistent
retrieval, explicit memory capture, and suggestion analysis. Neither mode
guarantees physical erasure from Python, native libraries, Ollama, the operating
system, swap, backups, or crash diagnostics.

Future versions may add bounded worker agents. Worker agents will receive limited tasks and permissions from the coordinator rather than unrestricted access.

## Data boundaries

- Source code, tests, and documentation are committed to Git.
- Secrets, personal data, databases, browser state, logs, and model files remain local and are excluded from Git.
- Audit logs are a diagnostic record, not canonical memory. They must be
  bounded, redacted, local, and independently replaceable.
