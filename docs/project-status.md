# Project Status

This document is the handoff point between coding sessions. At the end of each session, update the current status, outstanding actions, and session history below.

## Current status

- Module 0 and the Module 0.1 hardening gate are complete: Git safety rules,
  project documentation, source layout, virtual environment, project metadata,
  deterministic security boundaries, a local model adapter, and a runnable chat
  are in place. The Module 1 persistent-memory specification, bounded redacted
  audit writer, synthetic SQLCipher connection boundary, and checksummed
  forward-only migration layer are implemented. Typed encrypted repository
  operations now cover records, revisions, entities, links, lifecycle, and the
  permanent deletion ledger using synthetic data only. Deterministic retrieval
  now filters and ranks confirmed records through an encrypted FTS5 index,
  enforces record and token ceilings, and returns content-free receipts. A
  trusted capture coordinator now supports explicit confirmed memories and
  bounded, expiring, quarantined model suggestions connected through a
  post-response worker. A consistent encrypted daily-snapshot policy now
  supports scheduler invocation and enforces
  verification, count and byte retention, exact high-risk restore approval,
  pre-restore preservation, migration checks, deletion-ledger reapplication,
  atomic replacement, and rollback on failed final verification. A narrow chat
  adapter now retrieves only eligible confirmed records and inserts them as a
  bounded JSON data envelope explicitly labeled as untrusted. Synthetic restart
  recall passes. Portable recovery derives the database key for each session,
  a separate rate-limited passcode issues exact one-use approvals, and trusted
  administration covers setup, verification, metadata-only candidate listing,
  authenticated sensitive review, memory inspection and history, correction,
  privacy controls, lifecycle changes, profile assembly, permanent purge,
  backup, and restore. A new installation remains session-only until setup
  succeeds.
- Module 1.5 now has a lean native PySide6 foundation: masked first-run setup,
  recovery unlock before model loading, protected OS credential-store automatic
  unlock after one verified recovery entry, safe manual fallback, explicit
  session-only startup, streaming plain-text chat, fixed safe failures, bounded
  response selection, and graceful lifecycle shutdown. Credential reads and
  writes are content-free audited; unknown or plaintext backends fail closed.
  Both the native UI and terminal fallback use the same UI-neutral conversation
  service. Widgets receive no database, key, audit, approval, credential-store,
  or model authority objects.
- The native UI now has code-owned system/light/dark palettes, installed-font
  selection, and bounded global font sizing in backward-compatible versioned
  preferences. Its conversation sidebar automatically stores structured
  transcripts in the unlocked SQLCipher database, reopens them as continuable
  token-bounded chats, and supports permanent live-database deletion with an
  explicit backup-retention warning. Private Chat bypasses transcript storage,
  persistent retrieval, explicit memory capture, and suggestion analysis.
  Graceful window shutdown waits for an active response to finish its synchronous
  transcript commit and bounded accepted memory analysis before releasing
  database keys. Confirmed low-risk facts cross saved chats after a one-request
  handoff barrier. Explicit prior-chat recall uses a bounded encrypted FTS index;
  ordinary prompts still do not load other transcripts.
- The local permission policy is implemented and covered by automated tests.
- Module 2.0 has a code-owned deterministic tool registry and executor shared by
  native and recovery-terminal composition. Ollama receives native structured
  definitions for current local date/time and bounded decimal arithmetic.
  Every proposed execution is schema-validated, policy-checked, content-free
  audited, result-bounded, returned as untrusted tool-role data, and capped at
  three serial steps. Module 2.1 now adds an optional read-only search definition
  backed only by numeric-loopback SearXNG. Its query is derived only from the
  current user message and returned snippets are bounded untrusted data. Module
  2.2 adds request-scoped bounded text reading from numbered current search
  results, while browser, file, credential, shell, arbitrary URL fetch, and
  arbitrary-code tools remain disabled. The pinned SearXNG deployment now
  runs on demand in a dedicated one-GiB Colima profile and stops after two idle
  minutes or normal app shutdown.
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
- Project dependency management uses pinned `uv` 0.12.5, a committed
  cross-platform `uv.lock`, locked local synchronization, and locked CI
  execution. `setuptools` remains the package build backend.
- The local-only chat streams responses and has bounded session history while it
  is open. After trusted setup and recovery unlock, it retrieves only eligible
  confirmed persistent records, intercepts explicit remember instructions, and
  deterministically commits reviewed clear exact low-risk statements before the
  response while analyzing other completed turns asynchronously into
  quarantined candidates. It has the two reviewed local Module 2.0 utilities and
  the optional bounded SearXNG search path and numbered-result page reader, with
  no browser access, broad credential access, arbitrary page retrieval, or
  general network capability; the native
  composition alone receives a narrow automatic-unlock credential adapter that
  is never exposed to the model or widgets.
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
- Typed audit events accept no free-form message content. The replaceable local
  JSON Lines writer enforces restrictive permissions, event and file ceilings,
  bounded rotation, symbolic-link refusal, and safe failure messages. Portable
  security, approvals, memory analysis, encrypted database, migrations,
  repository operations, retrieval, capture, backup, and restore now emit typed
  events. Chat transcripts and ordinary response text are not logged.
- The encrypted database boundary pins `sqlcipher3` 0.6.2, requires SQLCipher 4
  cipher status, codec support, and FTS5, accepts keys only through a replaceable
  provider, refuses unsafe paths and plaintext fallback, blocks unused RTree
  helper functions and database attachment through a connection authorizer,
  and emits content-free database-open audit events. It has been tested only
  with synthetic data.
- The encrypted schema is built from 24 fixed, packaged, single-statement SQL
  migrations. Exact SHA-256 history is stored in the database; missing,
  duplicate, reordered, changed, unknown, or untracked history fails closed.
  The entire pending migration batch commits atomically or rolls back.
- Persistent memory uses one configured `memory.db`. Normal unlock requires that
  exact regular file to exist and cannot silently create a blank replacement;
  database creation is permitted only by explicit first-run setup. Missing or
  unsafe storage fails before model loading. A separate missing-live-database
  recovery design remains necessary because current restore intentionally
  expects a live deletion ledger and pre-restore snapshot.

## Outstanding actions

Work through these in order unless project needs change. Module 1 is locally
complete; the batched Linux pull-request check is its final platform gate.

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
- [x] Module 1 prerequisite: implement the bounded, redacted audit writer before
  persistent personal-data operations are enabled.
- [x] Module 1: select SQLCipher behind a replaceable encrypted SQLite and key-
  provider boundary; verify it locally on macOS ARM64 using synthetic data.
- [x] Module 1 portability: confirm the pinned SQLCipher boundary in the batched
  Linux GitHub Actions run. Windows verification remains a documented release
  gate before distributing a packaged Windows build.
- [x] Module 1: implement and test the checksummed migration runner and initial
  encrypted schema using synthetic data only.
- [x] Module 1: implement typed records and payloads, append-only revision
  snapshots, entities, aliases, record and entity links, lifecycle transitions,
  optimistic concurrency, candidate expiry, and the permanent deletion ledger.
- [x] Module 1: implement bounded retrieval and retrieval receipts.
- [x] Module 1: implement explicit remember and quarantined automatic memory-
  suggestion workflows.
- [x] Module 1: implement encrypted backup, verification, and guided restore.
- [x] Module 1: integrate bounded persistent context into chat and verify
  restart-persistent synthetic recall.
- [x] Module 1 deployment gate: implement portable key onboarding, verified
  recovery, trusted passcode approval, candidate review, and runtime wiring.
- [x] Module 1.5 foundation: add a native setup, recovery/automatic unlock,
  session-only, and streaming-chat interface over a narrow application-service
  boundary.
- [x] Module 1.5 conversation experience: add code-owned appearance controls,
  automatic encrypted transcript persistence, continuable sidebar history,
  Private Chat, deletion, and graceful shutdown finalization.
- [x] Module 1.5 owner controls: add a compact native memory inventory, exact
  source navigation for newly linked chat memories, and audited soft deletion
  without exposing authority objects to widgets.
- [x] Module 1.5 reconciliation engine: add bounded review values, edit,
  confirmation, rejection, conflict comparison, atomic correction, dated
  successors, stale-write protection, and exact protected-memory approvals.
- [x] Module 1.5 contextual memory: add an encrypted named-scope registry,
  conservative explicit phrase recognition, and deterministic scoped retrieval.
- [x] Module 1.5 owner controls: add opaque-cursor memory pagination, encrypted
  backup destination/create/guided restore, and bounded redacted audit viewing.
- [ ] Deferred Memory Review: redesign the hidden review experience later from
  practical usage; keep the tested reconciliation engine intact meanwhile.
- [x] Module 1.5 usability gate: complete headless native visual acceptance,
  primary-control accessibility names, keyboard navigation, and full local tests.
- [ ] Deferred release gate: package and sign the macOS app and verify packaged
  recovery and shutdown. Keep Windows packaging and runtime verification as a
  required later gate.
- [x] Module 2.0: define and implement the assistant's first code-owned tool
  registry, native Ollama tool-call protocol, deterministic permission and audit
  path, bounded executor, and safe local time and calculator tools.
- [ ] Deferred at owner direction: run the Module 2.0/2.1 Linux pull-request
  portability workflow. Do not describe it as verified meanwhile.
- [x] Module 2.1 code boundary: add user-derived read-only public search through
  fixed numeric-loopback SearXNG, with bounded inert results, citations,
  timeouts, duplicate suppression, policy enforcement, and content-free audit.
- [x] Module 2.1 runtime gate: install the approved open-source Colima runtime,
  start the pinned loopback-only SearXNG deployment, verify a real search, and
  verify literal 120-second idle shutdown.
- [x] Module 2.2: bind numbered page selections to current correlated search
  results, pin public DNS addresses under hostname-verified TLS, extract bounded
  inert text, auto-read broad news results, and verify a cited real-app current-
  events synthesis.
- [x] Module 2.3: add persistent quality-source routing, trusted search lifecycle
  controls, exact single-provider commands, one safe retry with fixed diagnostic
  codes, configurable idle shutdown, and cooperative generation cancellation.
- [x] Module 2.4: ground searched answers across distinct current documents,
  validate exact current-request citation provenance, and add an explicit
  owner-requested tool-free second model review.

## Session history

### 2026-08-27 — Module 2.4 evidence-grounded search verification

Completed:

- Clarified provider versus evidence-source semantics. A Scholar-only route uses
  one discovery provider while retaining several distinct papers or documents
  for comparison.
- Strengthened every searched answer's instructions to prefer primary or
  authoritative material, map important claims to exact citations, remove or
  qualify unsupported precision, and disclose conflicts, freshness limits, or
  single-document support.
- Added deterministic current-request citation provenance validation. Searched
  answers are buffered and rejected rather than presented as verified when they
  contain no current citation, cite an unknown URL, or have no usable results.
- Added explicit `double-check`, `verify this`, and `check your work` handling.
  The first answer remains an unshown draft; one tool-free second pass receives
  only the current question, bounded current evidence, and draft. Only its
  validated final answer reaches history and memory processing.
- Expanded provider intent recognition beyond rigid templates. Natural phrases
  such as `check Google Scholar search for info on...`, `use Crossref to
  find...`, and `look it up with PubMed` select only that enabled provider.
- Preserved bounded published-date metadata when SearXNG supplies it, as well as
  response cancellation during either generation pass.
- Fixed natural trailing-provider requests when ordinary prose follows the
  provider name, and added `disorder` to the health-search fallback vocabulary.
- Added native handling for `/long <question>` so the command changes the
  response limit but never contaminates the outbound search query.
- Added one bounded citation-repair pass for an otherwise successful search
  whose first model draft omits or alters current-result links. Failed repair
  still fails closed, and explicit evidence review never triggers a third pass.
- Replaced model-authored visible URLs with code-owned source IDs. Search answers
  now show readable source names by default and expose exact validated URLs only
  when the current message asks for links, URLs, or web addresses.
- Confirmed that provider selection is message-scoped: an explicit PubMed
  request does not pin a later unnamed treatment follow-up to PubMed-only
  routing.
- Added a domain-neutral conversational search resolver for pronouns and
  elliptical follow-ups. It uses only bounded recent user-authored topics,
  rejects private/credential-like context, ignores assistant, memory, and tool
  text, preserves newly named current topics, and asks for clarification when
  safe resolution is not possible.

Verification:

- All source and test modules compiled, the dependency lock and repository
  whitespace checks passed, and 467 local tests passed in 13.586 seconds with
  one intentionally opt-in benchmark skipped.
- A real Google Scholar-only double-check compared current evidence and produced
  a completed reviewed answer with three exact citations from distinct papers.
  Managed close stopped the dedicated Colima profile afterward.
- The exact reported `/long look up ... on pubmed, and ...` request then passed
  end to end, returned a completed high-level answer, and included three exact
  current PubMed-route citations.
- A real follow-up, `Is lamotrigine a typical treatment for it? What does it
  do?`, completed through automatic health routing, synthesized the retrieved
  material, displayed source names with zero visible URLs, emitted no failure
  notice, and stopped the dedicated search VM on close.
- The exact reported Janis Joplin follow-up resolved `her` to the topic copied
  from the preceding user turn, sent `can you give me some popular books on
  Janis Joplin?`, returned a synthesized five-book answer with a readable source
  name and zero visible URLs, emitted no notice, and completed normally.

Next:

- Owner UI test before updating the existing feature pull request workflow.

### 2026-08-27 — Module 2.3 quality search controls and cancellation

Completed:

- Added persistent allowlisted search-source settings with quality-first routes
  for general, scholarly, health/science, and reference requests. DuckDuckGo is
  available but disabled by default.
- Added exact current-message provider commands. Disabled explicit providers
  fail with `WEB-PROVIDER-01` and never silently fall back.
- Added trusted Settings controls for service status, manual start,
  finish-then-stop, and 1/2/5/10/15/30-minute idle shutdown. Changes run outside
  the UI thread; eligible later questions can restart search automatically.
- Added one bounded retry for transient start/connect/response failures and
  content-free fixed diagnostic codes.
- Added cooperative generation Stop. Partial text remains visible with a
  stopped notice, while the incomplete turn is excluded from conversational
  history and automatic memory promotion.
- Deferred an opt-in user-owned VPN/proxy search layer and reviewed runtime
  update workflow without adding either authority to the model.

Verification:

- All source and test modules compiled, repository whitespace checks passed,
  and 440 local tests passed in 13.630 seconds with one intentionally opt-in
  benchmark skipped.
- The real pinned SearXNG runtime returned five bounded Google Web results and
  five bounded results for an exact Google Scholar-only request. Managed close
  then stopped the dedicated Colima profile.

Next:

- Owner UI test before opening the pull request.

### 2026-08-26 — Module 2.2 bounded public page reading

Completed:

- Added `read_current_search_results`, which accepts one to three result numbers
  and resolves them only against URLs saved under the current search correlation
  ID. The one-use set is consumed on read and cannot cross requests.
- Added a raw-socket HTTPS reader that rejects non-HTTPS URLs, credentials,
  alternate ports, redirects, proxies, cookies, authentication, compression,
  non-text types, and any DNS answer that is not globally routable. The socket
  connects to a pinned validated address while TLS verifies the original host.
- Bounded each page to a 512-KiB transferred prefix and 1,200 visible characters,
  each request to three sequential pages, and the complete tool result to 5,500
  bytes. Script, style, noscript, template, and SVG content is removed.
- Labeled all extracted content untrusted and instructed the model to ignore
  page-borne directions, synthesize evidence, cite exact result URLs, compare
  sources, and disclose evidence limits.
- Added deterministic broad-current-events recognition. After a successful
  classification, code performs search and reads the first three available
  results before Qwen's first generation turn. Current-news retrieval therefore
  does not rely on Qwen recognizing that it lacks current knowledge or
  requesting either tool.
- Corrected the 16K context reservation to cover the real search-then-read path
  instead of three impossible maximum-sized page results. Page reading is now a
  coordinator-enforced terminal tool step, leaving room for the final answer and
  the maximum configured communication-style preference even when the full
  2,000-token response allowance is selected.
- Made the up-front tool reserve proportional to the active model context: it
  may use at most half of the post-response request budget. Fixed page/result
  security ceilings remain unchanged, while 8K, 16K, and larger configured
  windows preserve room for their own prompt and trusted instructions.
- Replaced the free-form context-window field with exact 8K, 16K, 32K, 64K,
  and 128K UI presets. The selected label persists its exact token value.
- Added a hard caller deadline and four-worker ceiling around public page
  fetching. Per-socket timeouts remain in place, while a hostile slow-drip
  server can no longer hold the conversation open indefinitely.
- Aligned environment and desktop resource validation so every context/response
  combination preserves at least 1,024 tokens for model input.

Verification:

- Private and mixed DNS answers, redirect status, unsafe URL forms, unsupported
  charset, active markup, stale request IDs, model-authored query data, and
  cross-request page selection have focused regression coverage.
- The real application factory under a Spotlight-style environment processed
  “Update me on major current events today,” audited both search and public-page
  reading as succeeded, returned a synthesized five-item update with exact HTTPS
  source links, emitted no error notice, and closed the managed runtime cleanly.
- The live approximately 64K model stack processed both “Tell me some recent
  news about Iran” and “Give me some current events on Iran,” automatically
  searched and read bounded public pages before generation, and returned
  concrete cited updates rather than a real-time-access refusal or list of
  search-result links.
- `uv lock --check`, source/test compilation, Git object integrity, credential
  signature review, and whitespace validation passed. The complete local suite
  passed 422 tests in 13.676 seconds, with only the intentionally opt-in
  100,000-record memory benchmark skipped.

### 2026-08-26 — Module 2.1 open-source read-only search boundary

Completed:

- Chose self-hosted SearXNG instead of a paid/proprietary search API or a broad
  scraping library. Kept a replaceable provider protocol so the local search
  implementation can change without changing model or executor contracts.
- Added a fixed numeric-loopback JSON adapter with no proxy discovery, redirect
  following, cookies, page retrieval, result URL fetching, credentials, or
  arbitrary destination selection. The adapter bounds timeout, response bytes,
  JSON shape, result count, title, snippet, and HTTPS URLs.
- Added deterministic query derivation: the model can request a search but
  supplies no outbound query. Code uses only the bounded normalized current user
  message and ignores model-authored query text, preventing appended memory
  values or other model-authored data from reaching search.
- Labeled all results as untrusted web data, strengthened the system instruction
  against result-borne prompt injection, required exact returned source URLs for
  search-supported claims, and stopped duplicate exact search attempts.
- Added a pinned, loopback-published, read-only SearXNG container definition with
  a small reviewed engine set, moderate safe search, JSON-only responses, no
  autocomplete or image proxy, short upstream timeouts, and no retries.
- Added app-owned Colima lifecycle management. The dedicated profile is capped
  at one GiB and two CPUs, mounts only the reviewed configuration directory
  read-only, starts on first search, resets its timer after each search, and
  stops after 120 idle seconds or normal app shutdown. The model has no
  lifecycle or container authority.
- Rejected Podman after its real macOS gate exposed current VM forwarding and
  startup failures. Colima with macOS Virtualization.Framework passed the same
  stability, real-search, and shutdown gates.
- Live audit showed that prompting Qwen to copy an exact query, including a
  bounded retry, remained unreliable. Removed query authorship from the model
  contract entirely rather than weakening the exfiltration boundary.
- Added a pre-search liveness check so cached in-process runtime state cannot
  outlive the actual VM or container. If the dedicated service was stopped
  externally, the app now re-establishes the bounded runtime before searching.
- Added a fixed trusted Homebrew and macOS system command path for the managed
  runtime. Spotlight/Finder's minimal environment no longer prevents Colima
  from locating its Lima dependency, and arbitrary inherited path entries are
  not trusted.

Verification:

- A real generic public search returned bounded HTTPS results through the pinned
  SearXNG image, and managed close removed the listener and stopped the VM.
- An independent agent launched the real application factory with real Qwen and
  SearXNG under a Finder/Spotlight-style minimal environment. An ordinary current
  factual question triggered `web_search` audit events from `started` to
  `succeeded`, returned an exact HTTPS citation with no search notice, and clean
  shutdown stopped the VM and removed the loopback listener.
- A literal 125-second observation confirmed the dedicated runtime stopped after
  its 120-second inactivity threshold.
- `uv lock --check` passed, all source and test modules compiled, and the full
  local suite passed: 407 tests in 13.743 seconds, with only the intentionally
  opt-in 100,000-record memory benchmark skipped.

Next:

- Add trusted Settings status, manual override, idle-time, and reviewed-update
  controls later without exposing lifecycle authority to the model.

### 2026-08-26 — Module 2.0 bounded local tool foundation

Completed:

- Specified the first model-to-tool boundary before enabling capability. The
  initial scope contains only local current date/time and bounded decimal
  arithmetic; web, browser, files, credentials, shell, and arbitrary evaluation
  remain explicitly excluded.
- Extended the replaceable model contract and Ollama adapter with bounded native
  tool definitions, structured calls, assistant call messages, and distinct
  tool-result roles. Ordinary no-tool responses retain streaming behavior.
- Added a code-owned registry and executor that resolve exact names, validate
  canonical arguments, apply the existing permission policy, fail closed when
  start auditing is unavailable, and return only bounded JSON labeled as
  untrusted tool data.
- Added one-call-per-step and three-step-per-request coordinator ceilings.
  Parallel, malformed, conflicting-index, unknown, unauthorized, excessive, and
  invalid calls cannot reach a handler. Internal tool messages are not retained
  as ordinary conversation history.
- Wired the same executor into native and recovery-terminal session composition
  without exposing registry, audit, approval, model, or database authority to
  widgets.
- Verified all 380 local tests; one opt-in performance test remained skipped.
  Focused tool/model tests, source and test compilation, dependency-lock
  consistency, and diff whitespace checks also passed.

Next:

- Commit the locally verified Module 2.0 milestone, then use one batched pull
  request for its Linux portability gate when ready.
- Design Module 2.1 read-only web search as a separate network, redirect,
  provenance, prompt-injection, citation, cancellation, and approval gate.

### 2026-08-26 — Pre-PR blocker remediation

Completed:

- Converted passcode verification and lockout failures during native restore
  into fixed application-service errors, so they remain inside the trusted UI
  boundary instead of escaping through the Qt event loop.
- Isolated memory, audit, and backup Settings loading. A missing or disconnected
  external backup destination now leaves Settings open and provides a replacement
  folder path instead of trapping the owner outside configuration.
- Validated a new backup destination before persisting it or replacing the live
  manager. Moved destination checks, full ciphertext hashing, snapshot creation,
  and guided restore to a dedicated Qt worker thread.
- Made native shutdown wait for an active backup operation to complete before
  closing the encrypted runtime. Conflicting Settings controls remain disabled
  while the worker owns the operation.
- Kept Settings, New chat, Private chat, and saved-chat navigation available
  while a response streams. A read-only conversation view prevents background
  navigation from replacing the active model context; the requested destination
  becomes active only after the current turn commits. Stream events are routed
  away from unrelated transcripts and rapid token chunks are repaint-batched.
- Added `docs/open-bugs.md` for two deliberately deferred P2 defects: unstable
  audit offset pagination under concurrent appends and session-only visibility
  of content-minimized owner audit history.
- Verified all 363 local tests; one opt-in performance test remained skipped.
  Dependency consistency and compile checks also passed.
- PR #8's first Linux run reached the UI test import after 343 successful tests,
  then exposed a missing runner dependency: `libEGL.so.1`. The workflow now
  installs only the required `libegl1` runtime package before the locked project
  install, and a repository-safety assertion keeps that CI prerequisite visible.

Next:

- Confirm PR #8's replacement Linux run imports and exercises the native UI.
- Keep the two documented P2 audit defects visible for the following maintenance
  pass.

### 2026-08-26 — Module 1.5 owner controls and usability gate

Completed:

- Added stable opaque-cursor pagination for the memory inventory. Pages remain
  bounded to 100 raw records, and a non-content canonical identity prevents the
  same logical memory from reappearing when older pages are appended.
- Added native encrypted-backup controls for choosing and persisting an existing
  destination, creating a fully verified managed snapshot, viewing bounded
  metadata, and restoring only a managed snapshot. Restore requires exact
  `RESTORE` confirmation plus the high-risk passcode, verifies the encrypted
  database, creates a pre-restore safety snapshot, reapplies the deletion ledger,
  and refreshes live memory and conversation views.
- Added a newest-first audit reader and native Audit trail page. It reads rotated
  regular files without following symbolic links, rejects malformed entries,
  caps display at 1,000 events, and exposes only allowlisted timestamp,
  component, operation, outcome, and reason fields.
- Added primary-control accessibility names and keyboard navigation across active
  Settings pages. Performed headless light/dark visual checks at the standard
  native window size and corrected navigation and table truncation.
- Kept the dense Memory Review page out of active navigation and documented its
  redesign as a future usage-informed feature. Kept signed macOS packaging and
  Linux Actions/PR execution deferred for owner review.
- Verified all 360 local tests; one opt-in performance test remained skipped.

Next:

- Owner-review the native settings flow locally before any push or pull request.
- After approval, run the batched Linux pull-request gate, then define the first
  tool registry and permission-enforcement path.

### 2026-08-26 — Native memory inventory and exact source navigation

Completed:

- Added a dedicated Settings navigation layout whose default Memory page uses a
  stable broad-category sidebar, local search, and one dense
  value/kind/status/update/actions table. Widgets receive immutable bounded rows
  rather than repository or database objects.
- Made the normal inventory canonical: it shows confirmed usable memory and
  clearly labeled tentative observations, collapses conservative exact-content
  equivalents, and hides raw fact candidates, archived records, question-shaped
  fragments, and context-dependent fragments without deleting audit history.
- Hardened automatic capture so missing-punctuation questions cannot be promoted
  as facts and model-generated background facts or trivia without exact
  standalone user evidence are discarded. Retrieval independently excludes
  legacy invalid direct statements and equivalent duplicate content.
- Added a global Communication Style settings panel. Free-form style text is
  bounded, validated, encrypted, append-only revisioned, content-free audited,
  and applied immediately to subsequent replies through a style-only system-data
  envelope that cannot grant authority or weaken safety rules.
- Preserved the tested candidate-reconciliation engine but removed its first
  dense Memory Review page from active Settings navigation. A simpler redesign
  is recorded in future features and should be informed by actual suggestion-
  review value rather than presenting every lifecycle choice immediately.
- Protected candidate values remain redacted until passcode-backed review.
  Protected decisions bind approval to the exact decision, content digest,
  record versions, target, and effective date; widgets never receive approval
  receipts or authority objects.
- Added encrypted named contextual scopes for explicit phrases such as `At
  work, ...`, `For project Apollo, ...`, and `When discussing family plans,
  ...`. Complete-label matching activates them during retrieval; outside that
  context they remain excluded. Ambiguous phrasing stays global rather than
  letting the model invent a scope.
- Linked newly created chat-derived memories to the exact opaque encrypted user
  message ID. View source resolves the ID directly, opens the correct saved
  conversation, and highlights the exact sequence even when text is duplicated.
- Preserved deletion honesty: removing a chat cascades its source messages, so
  the memory remains but source lookup returns a fixed deleted-or-unavailable
  error. Older memories use a strict compatibility lookup only when their
  literal saved text occurs in exactly one surviving user message; ambiguous,
  inferred, deleted, and imported sources are never guessed.
- Kept memory deletion recoverable: the row leaves ordinary retrieval while its
  revision history and content-free audit event remain.
- Verified all 352 local tests under the locked `uv` environment; one opt-in
  performance test remained skipped.

Next:

- Let the owner review the native Settings changes before any push or pull
  request.
- Run the intentionally deferred Linux pull-request gate only after that review.
- Keep the Memory Review redesign and signed macOS packaging deferred.

### 2026-08-26 — Tentative observation layer

Completed:

- Added low-confidence observation proposals to bounded post-response analysis.
  They are model-authored insight candidates with no exact-user-evidence
  auto-confirm path, a 30-day expiry, conservative personal sensitivity, and no
  authority over confirmed memory.
- Added opt-in repository retrieval for eligible normal or personal insight
  candidates only. Candidate facts and preferences, expired observations, and
  sensitive or restricted content remain quarantined. Confirmed records consume
  bounded record and token capacity first.
- Separated observations from canonical `memories` in the inert JSON context.
  The model is told they may be situational, time-specific, or a potential
  challenge to a confirmed default, but may not silently overwrite facts,
  authorize actions, or diagnose.
- Preserved the explicit-confirmation boundary for future reconciliation as a
  global revision, time-bounded change, or scoped exception. Native review and
  reconciliation controls remain unimplemented Module 1.5 owner controls.
- Verified all 324 local tests; one opt-in performance test remained skipped.

Next:

- Add native candidate/observation review and an explicit reconciliation screen
  that shows the proposed change before applying it.
- Exercise observation capture and cross-chat retrieval in the native app with
  situational wording and a deliberate fact conflict.

### 2026-08-26 — Deterministic global memory and standing retrieval approval

Completed:

- Removed the model-analysis dependency from reviewed clear direct facts. The
  exact current-user sentence is classified and committed synchronously before
  the main response, even when the model returns no suggestion JSON.
- Applied standing owner approval to relevant confirmed personal memory, so new,
  current, and reopened saved chats use the same global canonical records without
  repeatedly asking whether to check memory. Direct-only, never-mention,
  restricted, prohibited, and unconfirmed content keeps its stronger boundary.
- Broadened natural explicit transcript recall to phrases such as “have we
  discussed,” “did we talk about,” and “do you remember,” while preserving
  bounded encrypted search, active-chat exclusion, and inert-data handling.
- Preserved current-fact precedence: retrieved confirmed records are ordered by
  trusted update time and override stale statements in reopened historical
  transcripts; contradictions still require clarification instead of silent
  overwrite.
- Verified 318 tests locally with the normal performance test skipped.

Next:

- Retest the native app with name, broad residence, pet, and gluten-sensitivity
  facts across a new chat, a reopened old chat, and an app restart.
- Continue with native candidate review and backup/restore controls.

### 2026-08-26 — Cross-chat memory handoff and explicit transcript recall

Completed:

- Diagnosed a real cross-chat miss without reading personal content. The first
  response had committed, but asynchronous memory analysis finished about four
  seconds later and the model's paraphrase lacked a verified exact evidence
  quote, so the result correctly remained an unconfirmed candidate excluded from
  the next chat.
- Added an idle-tracked post-response handoff. The first persistent request after
  new/open waits boundedly for accepted preceding analysis, and graceful shutdown
  waits before cancelling any remaining work.
- Added conservative lexical evidence binding. A unique model paraphrase may
  select an exact first-person declarative sentence, but only that original user
  sentence is confirmed. Ambiguous selections remain quarantined.
- Added forward-only encrypted transcript-search migrations with backfill for
  existing saved chats. Explicit history requests search at most three chats and
  four nearby messages each, exclude the active chat, and place excerpts in a
  token-bounded untrusted JSON envelope. Ordinary prompts and Private Chat do not
  search transcripts.
- Rechecked the feature against the owner's content-free live audit after the
  first real retest failed. The updated migrations had applied and the relevant
  direct statement was confirmed, but natural prior-session wording did not
  trigger transcript search and a singular/plural query mismatch returned no
  memory context. Broadened deterministic history intent, added a one-turn
  referential retrieval hint, recognized direct self-questions, and normalized
  conservative English inflections without recording personal content.
- Added shared deterministic word normalization and reviewed topic connections
  for direct memory and explicit transcript recall. Clear durable-looking
  first-person statements now finish capture before the main response; trusted
  italic receipts report only generic topics, while contradictions and
  uncertainty ask for clarification without overwriting confirmed data.
- Added a transient no-token thinking animation and a lightweight native arm64
  macOS development launcher for Spotlight and Dock access to the live `uv`
  checkout. The launcher is ad-hoc signed locally, not a signed or
  self-contained release package.
- Fixed reopened-chat precedence: confirmed memories now carry trusted update
  timestamps in the bounded context envelope, newer conflicting memory is
  ordered first, and the system contract makes canonical memory override stale
  details in an older restored transcript.
- Verified 313 tests locally with the normal performance test skipped. The
  separate 100,000-record encrypted retrieval benchmark passed at 13.99 ms
  median and 14.26 ms p95 over 30 queries.

Next:

- Exercise a real first-chat fact handoff and an explicit “remember when” query
  in the native app after restart.
- Continue with native candidate review and backup/restore controls.

### 2026-08-26 — Appearance and encrypted conversation sidebar

Completed:

- Extended backward-compatible native preferences with system/light/dark theme,
  installed-font selection, and a bounded global font size. Themes use only
  code-owned palettes; preferences cannot inject arbitrary stylesheets.
- Added three forward-only encrypted migrations for conversation metadata,
  structured transcript messages, and deterministic message ordering.
- Added a narrow audited conversation-history repository. User messages commit
  before generation, assistant content commits synchronously before completion,
  and sidebar reads never expose database objects or load unrelated transcripts
  into model context.
- Added new, private, reopen-and-continue, and permanent-delete sidebar flows.
  Private Chat bypasses transcript storage, persistent-memory retrieval,
  explicit memory capture, and suggestion analysis.
- Changed graceful window shutdown to wait for an active response worker to
  finish transcript persistence before closing encrypted memory.
- Verified 290 tests locally with the normal performance test skipped. The
  separate 100,000-record encrypted retrieval benchmark passed at 14.07 ms
  median and 14.24 ms p95 over 30 queries.

Next:

- Exercise create, close, reopen, continue, Private Chat, and delete against the
  owner's real encrypted database in the native app.
- Continue with native candidate review and backup/restore controls.

### 2026-08-26 — Natural recall and exact-statement capture

Completed:

- Diagnosed live recall using only content-free audit events and aggregate
  encrypted-record metadata. The stable database contained 26 records: 9
  confirmed and 17 candidates. Confirmed residence and Scooby records existed,
  proving the immediate failure was retrieval rather than database loss.
- Removed conversational scaffolding from lexical queries and added a bounded
  partial-match fallback only when strict all-term FTS finds nothing. The live
  natural Scooby question now selects its existing confirmed record; the live
  residence question selects existing confirmed records.
- Treated an explicit question about a saved subject as consent to use an
  applicable ask-before record for that answer, while incidental use still
  requires a natural clarification and restricted/never-mention records remain
  excluded.
- Improved automatic capture by allowing an exact model-selected phrase to
  locate a complete declarative sentence in the current user message. Only that
  verified sentence can become confirmed; questions, paraphrases, credentials,
  sensitive content, conflicts, and inferences remain quarantined or rejected.
- Verified 267 tests locally with the normal performance test skipped. The
  separate 100,000-record encrypted retrieval benchmark passed at 13.80 ms
  median and 14.04 ms p95 over 30 queries.

Next:

- Restart the native app and verify natural questions about the already
  confirmed residence and Scooby records.
- Add native candidate review so the 17 existing quarantined suggestions can be
  inspected and confirmed or rejected without command-line work.

### 2026-08-26 — Biometric launch gate and native runtime settings

Completed:

- Added native macOS device-owner authentication before the application reads
  its stored Keychain recovery passphrase. The system accepts Touch ID or the
  Mac login password, and may also accept a paired Apple Watch when enabled;
  cancellation and unavailable authentication fall back to trusted recovery
  entry before model loading.
- Verified a real synthetic Local Authentication then Keychain read on macOS;
  the temporary credential was deleted afterward. Apple rejected direct
  Keychain-item access control for the unsigned development process with the
  expected missing-entitlement status, so signed-package item binding remains
  an explicit release gate rather than an overstated current guarantee.
- Added Enter-to-send with Shift+Enter for multiline prompts and removed the
  missing-font alias warning by selecting installed platform fonts explicitly.
- Added a native settings page for a bounded context window, default response
  limit, and response ceiling. Changes are atomically persisted for the next
  launch, content-minimally audited, and rolled back if required auditing fails.
- Kept the code-enforced 2,000-token response maximum and required at least
  1,024 context tokens to remain available for input.
- Verified 281 tests locally with the normal benchmark skip. The separate
  100,000-record encrypted retrieval benchmark passed at 13.83 ms median and
  14.02 ms p95 over 30 queries.

Next:

- Restart the app, approve the native macOS authentication prompt, and verify
  chat opens using the existing Keychain credential.
- Package and sign the macOS `.app`, then bind user presence directly to the
  Keychain item before distribution.

### 2026-08-26 — Protected automatic unlock

Completed:

- Added a narrow OS credential-store adapter so the native app can enroll the
  recovery secret only after a successful database unlock and then start later
  sessions without a recovery-passphrase prompt.
- Kept the portable recovery passphrase and high-risk passcode separate. Missing,
  unavailable, or stale automatic-unlock material falls back to the trusted
  recovery screen before model loading and never creates a new database.
- Restricted production use to reviewed protected keyring backends, pinned and
  hash-locked `keyring` 25.7.0, and explicitly excluded plaintext fallback.
- Added content-free audit events for credential reads and enrollment without
  credential values, OS account names, or data paths.
- Verified the real macOS Keychain with a temporary synthetic write/read/delete
  round trip; the temporary credential was removed afterward.
- Verified 261 tests locally; the opt-in 100,000-record retrieval benchmark is
  the only normal-suite skip. Windows and Linux credential backends remain
  explicit platform verification gates.

Next:

- Enter the recovery passphrase once in the native app to enroll the existing
  encrypted database, then verify the following launch reaches chat without a
  passphrase prompt.
- Continue with native candidate review and memory owner controls.

### 2026-08-25 — Module 1.5 native UI foundation

Completed:

- Added a native PySide6-Essentials interface with masked setup and unlock,
  session-only startup, streaming chat, bounded response selection, inert
  plain-text rendering, and off-thread model work.
- Added a narrow application service that owns memory/runtime lifecycle and
  exposes only immutable session details and sanitized conversation events.
  Failed recovery unlock occurs before model construction.
- Consolidated the terminal recovery interface and native interface onto one
  bounded conversation service for structured roles, session history, persistent
  context, explicit memory, model failures, token limits, and post-response work.
- Added headless UI and service tests for secret clearing, authority isolation,
  failed-setup cleanup, failed-unlock ordering, concurrent-request refusal,
  inert rendering, busy-state enforcement, invalid limits, and shutdown.
- Pinned the minimal Qt Essentials dependency through the existing `uv` lock.
  No browser runtime, UI server, telemetry, tool access, or new network service
  was introduced.
- Verified 254 tests locally; the opt-in 100,000-record retrieval benchmark is
  the only normal-suite skip. Its separate run passed at 13.56 ms median and
  13.93 ms p95 over 30 queries.

Next:

- Commit this visually reviewed local milestone without pushing until a batched
  GitHub Actions run is desired. Then add native owner-control panels through
  the same narrow service boundary.

Follow-up:

- Diagnosed a first-run setup rejection through the content-free audit trail.
  The deterministic validator correctly rejected invalid secret shape while
  cleanup left no manifest or database, but the UI-facing service replaced its
  safe correction with a generic message. Setup now displays only five explicitly
  whitelisted corrections for confirmation, minimum length, or distinct-secret
  failures; all other details remain hidden behind the generic safe failure.
- Verified the live default data directory contained no manifest or database
  after the rejected setup. Hardened both the application factory and shared
  memory runtime so normal startup cannot create a missing database; only the
  explicit setup workflow may create it.
- Replaced the unnamed Qt font request with the platform application font and
  added inert native formatting for assistant headings, lists, bold emphasis,
  and inline code. Streaming stays immediate; formatting is applied on completion
  without enabling HTML, active links, or remote resources.
- Diagnosed cross-session recall through content-free audit events: the encrypted
  database reopened correctly and automatic analysis persisted candidates, but
  ordinary retrieval correctly excluded their unconfirmed status while the UI
  offered no review path. Exact low-risk evidence copied from the current user
  message can now become confirmed automatically. Only the exact quote is stored;
  model-authored subjects and paraphrases are discarded. Inferences, mismatches,
  sensitive evidence, and conflicts remain quarantined. An encrypted close/open
  test verifies recall in a new runtime.

### 2026-08-25 — Module 1 final security and privacy review

Completed:

- Made repository writes, migrations, backup publication, and restore swaps
  fail closed when their success audit cannot be durably recorded.
- Hardened prohibited-secret validation against Unicode, invisible, spaced,
  one-time-code, and valid payment-card forms; expanded deterministic identity
  sensitivity classification.
- Added monotonic approval expiry, serialized thread/process passcode checks,
  safer setup rollback, worker survival, and runtime key cleanup on startup
  failures.
- Connected ask-before and direct-only mention policies to natural chat flow;
  restricted memories still never enter model context.
- Added metadata-only candidate and memory inventories plus trusted inspection,
  revision history, correction, privacy controls, lifecycle, entity profile,
  and permanent-purge commands with passcode gates at sensitive boundaries.
- Blocked unused RTree helper functions and database attachment through the
  SQLCipher connection authorizer while retaining the pinned encrypted driver.

Verification:

- The complete local suite passes 229 tests with one opt-in performance test
  skipped in the ordinary run.
- The separate 100,000-record encrypted retrieval benchmark passes at 14.02 ms
  median and 14.92 ms p95 over 30 queries, with 96 candidates examined, 12
  records returned, and 1,295 conservatively estimated memory tokens.

### 2026-08-25 — Module 1 portable deployment gate

Completed:

- Added a versioned, cross-platform recovery manifest using scrypt-derived
  SQLCipher keys and salted verification checks. Recovery and approval secrets
  are never stored, logged, passed as command arguments, or sent to the model.
- Added a separate high-risk passcode gate with persisted failed-attempt state,
  bounded lockout, redacted audit events, and exact short-lived one-use approval
  receipts. A correct passcode still cannot override a prohibited action.
- Added trusted local setup, recovery verification, candidate review, encrypted
  backup listing and creation, and guided restore commands. Restore binds the
  displayed snapshot metadata to approval and cancellation performs no change.
- Wired unlocked persistent memory into normal chat. Explicit remember requests
  are handled before model submission; automatic post-response analysis is
  asynchronous and can create only quarantined, expiring candidates.
- Added persisted content-free backup integrity metadata, unsafe-parent checks,
  and audit-directory symbolic-link refusal. Runtime shutdown cancels future
  candidate persistence before clearing the application-owned derived key copy.
- Kept operating-system automatic unlock, graphical configuration, key rotation,
  portable import/export, and Windows runtime verification as future gates.

Verification:

- The complete local suite passes 220 tests, with the synthetic 100,000-record
  performance benchmark separately passing at 13.18 ms median and 13.41 ms p95
  over 30 queries, with 96 candidates examined, 12 records returned, and 1,295
  conservatively estimated memory tokens.

Next:

- Run the opt-in retrieval benchmark, locked-environment verification, and
  repository safety checks; then push one batched branch update and let the
  pull-request workflow verify SQLCipher on Linux before auto-merge.

### 2026-08-25 — Persistent chat context and restart recall

Completed:

- Added a narrow repository-to-chat adapter. It can request only ordinary
  deterministic retrieval and receives neither keys nor an exposed SQL or
  database handle.
- Serialized eligible payloads into one bounded JSON object under a system
  instruction that treats every stored string as untrusted data, never as
  instructions, policy, or authority. User and assistant roles remain
  structurally separate.
- Preserved the 2,000-token persistent-memory ceiling and the full 16K request
  budget. Recent session turns are trimmed first; if persistent context itself
  prevents the current request from fitting, chat visibly continues without
  persistent memory instead of dropping the user request.
- Retrieval or database failure produces a fixed content-free notice and safely
  continues without memory. Low-information queries simply retrieve nothing
  rather than being reported as failures.
- Improved natural lexical recall with bounded FTS5 prefix matching, allowing a
  query such as `like` to match `likes` while retaining all existing status,
  scope, sensitivity, mention, time, candidate-count, record-count, and token
  limits.
- Reconstructed the database, repository, and context adapter around the same
  encrypted synthetic file to prove confirmed recall survives restart while a
  model candidate remains quarantined.
- Verified instruction-shaped stored text remains syntactically inside the JSON
  data object. It cannot become a separate model role and still cannot grant
  executor authority under the security doctrine. The model may still
  misinterpret untrusted text, so labeling is not treated as the security
  boundary.
- The 100,000-record encrypted benchmark reports 12.99 ms median and 13.20 ms
  p95 over 30 queries, with 96 candidates examined, 12 records returned, and
  1,295 conservatively estimated memory tokens.
- The complete local suite runs 195 tests successfully, with the opt-in
  performance benchmark skipped during the normal run and separately passing
  when enabled.

Next:

- Commit this final local Module 1 implementation gate. The next meaningful
  Actions-consuming milestone is the batched branch push and pull request,
  which will also verify the locked SQLCipher environment on Linux.
- Before accepting real personal data, implement portable key onboarding,
  recovery verification, and the trusted passcode interface. The default CLI
  remains session-only until that deployment gate is complete.

### 2026-08-25 — Encrypted backup and guided restore boundary

Completed:

- Added a configured external-destination backup manager using SQLite's online
  backup mechanism through verified SQLCipher connections. Live database files
  are never copied directly.
- Added an idempotent daily entry point for a future scheduler. It skips only
  after verifying the existing daily snapshot. No runtime schedule or external
  drive is configured yet.
- Added atomic publication from flushed encrypted partial files, owner-only
  POSIX permissions, and strict refusal of missing, symbolic-link, or
  unmanaged destinations.
- Enforced the approved defaults and hard ceilings of seven snapshots, 2 GiB
  per snapshot, and 10 GiB total. Retention runs only after a new snapshot has
  passed encryption, migration-history, integrity, and foreign-key checks.
- Added a content-free restore plan bound to the managed filename, ciphertext
  SHA-256, and live target. Restore consumes an exact short-lived one-use
  approval and rejects a snapshot changed after the plan was shown.
- Kept restore unavailable from normal chat. The engine requires an approval
  authority supplied by a future trusted passcode interface; tests use only a
  synthetic authority and do not create a production bypass.
- Restore copies into an encrypted temporary database, runs required forward
  migrations, creates a fresh pre-restore snapshot, reapplies the current
  deletion ledger, verifies the candidate, atomically replaces the live file,
  verifies again, and restores the prior live file if final verification fails.
- Added synthetic tests for encrypted consistency, daily behavior, retention,
  missing destinations, corrupt snapshots, post-plan tampering, exact approval,
  interrupted writes, rollback, and deletion-ledger preservation. The full
  suite passes with 189 tests and one intentionally skipped opt-in performance
  benchmark.

Next:

- Integrate persistent memory into normal chat with bounded retrieval and
  restart-persistent synthetic recall, while leaving automatic suggestion
  analysis asynchronous and quarantined.
- Add the trusted passcode entry UI before exposing guided restore or any other
  high-risk operation to a conversational or model-controlled path.

### 2026-08-25 — Explicit remember and quarantined suggestion workflows

Completed:

- Added typed explicit-memory requests, automatic model suggestions,
  content-free decisions, and a trusted capture coordinator. The API does not
  expose a status switch through which model output could request confirmed
  memory.
- Explicit normal or personal instructions create confirmed records. An exact
  confirmed duplicate is reused, an exact single candidate is confirmed, and a
  different value for the same subject returns opaque related IDs for natural
  clarification instead of overwriting history.
- Explicit sensitive or restricted capture pauses for a separate higher-risk
  review path. That path is not implemented by weakening the capture policy or
  accepting a conversational approval flag.
- Automatic suggestions always create 30-day candidate records. Conservative
  sensitivity and mention-policy floors tighten model proposals: notes and
  insights are at least personal, sensitive suggestions are direct-request
  only, and restricted suggestions are `never_mention`.
- Added deterministic sensitive and restricted content rules for known
  wellbeing, trauma, medical, financial, legal, location, and relationship
  categories. A model may raise the resulting classification but cannot lower
  it. These conservative rules are a replaceable policy layer, not a claim that
  keyword matching understands every possible sensitive nuance.
- Enforced a default maximum of three and hard maximum of five candidates per
  completed-turn source inside the encrypted write transaction. Changing the
  claimed model version cannot bypass the persisted turn limit.
- Added a small, cancellable post-response batch primitive. It is ready for a
  future background worker, but no analyzer or normal-chat integration invokes
  it yet, so this milestone does not automatically store live conversation
  content.
- Used the encrypted FTS5 index to bound exact duplicate and same-subject
  conflict discovery. Unrelated global records do not consume the 64-neighbor
  safety ceiling; an unexpectedly broad result fails closed for clarification.
- Added typed coordinator audit events for success, duplicate, clarification,
  higher-risk denial, candidate-limit, and failure outcomes. Events contain
  opaque IDs and counts but no memory, prompt, source-turn, or model text.
- Added synthetic tests for confirmation, duplicate suppression, conflicts,
  risk review, conservative controls, quarantine, retrieval exclusion,
  persisted candidate limits, cancellation, audit failure, audit redaction,
  credentials, and unrelated-memory scale behavior. No personal data or
  runtime database was created.

Next:

- Implement consistent encrypted backup, bounded retention, verification, and
  guided restore with deletion-ledger reapplication and exact high-risk
  authorization.
- Only after backup and restore pass should persistent memory be connected to
  normal chat and exercised with restart-persistent synthetic recall.

### 2026-08-24 — Deterministic bounded memory retrieval

Completed:

- Added a typed retrieval request, selected-memory result, and content-free
  receipt with selected opaque IDs, applied deterministic rules, exclusion
  counts for post-ranking resource limits, records examined, records returned,
  and conservatively estimated tokens returned.
- Added an encrypted FTS5 search index with non-content control fields so
  status, scope, sensitivity, mention policy, validity, and kind filters apply
  before the bounded candidate set is ranked.
- Ranked a maximum of 96 candidates by resolved entity, scope specificity,
  full-text relevance, memory kind, provenance, recency, and stable opaque ID;
  returned at most 12 records and 2,500 conservatively estimated tokens.
- Kept candidates, archived or deleted records, expired records, inapplicable
  scopes, `ask_before_mentioning`, and `never_mention` records out of ordinary
  retrieval. Direct mode may include `only_when_directly_asked` records, but
  restricted records remain unavailable until separate high-risk
  authentication is implemented.
- Updated the derived search index atomically on create, revision, lifecycle
  change, and purge. Added forward migrations that create and backfill the
  index from the current revision of an existing version-15 database.
- Added synthetic tests for privacy filters, direct-request policy, scope and
  entity ranking, count and token limits, revisions, purges, query injection,
  content-free auditing, migration backfill, and fixed parameterized SQL.
- Added an opt-in benchmark so normal PR CI does not spend its budget building
  a 100,000-record fixture. On the primary development Mac, 30 measured queries
  over 100,000 encrypted synthetic records reported 9.05 ms median and 9.31 ms
  p95 retrieval, 96 examined candidates, 12 returned records, 1,297 estimated
  tokens, and a 138,780,672-byte database.

Next:

- Implement explicit remember and quarantined automatic memory-suggestion
  workflows without connecting persistent memory to normal chat yet.
- Confirm SQLCipher, migrations, retrieval, and the locked `uv` environment in
  the eventual batched Linux pull-request run.

### 2026-08-24 — Typed encrypted memory repository and uv adoption

Completed:

- Added registered, bounded payload types for facts, preferences, events, notes,
  insights, and policy preferences; typed provenance, sensitivity, mention,
  scope, entity, alias, and link values; and conservative rejection of
  credential-associated or unsafe-control content.
- Added fixed parameterized repository methods for encrypted record creation,
  inspection, correction, control changes, candidate confirmation/rejection,
  archival, restoration, soft deletion, atomic supersession, bounded candidate
  expiry, and permanent purge.
- Stored a canonical full-envelope snapshot for every append-only revision,
  linked revision hashes, and enforced optimistic row versions so stale writes
  fail without overwriting newer state.
- Added stable entities, exact normalized aliases that preserve ambiguous
  matches, record and entity links, three-distinct-evidence enforcement for
  insights, feedback records, and purge-ledger suppression.
- Kept model output quarantined to expiring candidate records. It cannot create
  confirmed memory or directly change an existing memory, alias, or entity
  link.
- Added content-free repository audit events and synthetic encrypted tests for
  injection-shaped text, lifecycle rules, stale writes, ambiguity, tampering,
  purge, model-boundary attempts, and audit failure before mutation. The full
  suite passes with 154 tests.
- Installed and pinned `uv` 0.12.5, committed its cross-platform lockfile,
  required locked local and CI installs, and retained `setuptools` as the build
  backend.
- Kept all persistent-memory operations disconnected from chat; no real
  personal data, key, audit log, or runtime database was created.

Next:

- Implement deterministic bounded retrieval and content-free retrieval receipts
  over confirmed records only.
- Confirm the SQLCipher and locked `uv` workflow in the eventual Linux PR run;
  retain Windows as an explicit pre-distribution verification gate.

### 2026-08-24 — Checksummed encrypted schema migrations

Completed:

- Added 13 fixed, packaged, forward-only SQL migrations for the migration
  ledger, memory records and revisions, entities and aliases, record links,
  feedback, deletion ledger, and bounded lookup indexes.
- Added exact SHA-256 verification and strict contiguous ordering. The runner
  accepts stored history only when it is an exact prefix of the packaged
  history and refuses altered, missing, duplicate, reordered, newer, malformed,
  or untracked schema state.
- Applied the complete pending batch in one encrypted transaction so any failed
  statement rolls back all pending schema changes.
- Added content-free migration audit events and synthetic tests covering fresh
  migration, idempotent reruns, history tampering, source defects, rollback,
  untracked schema, audit failure, encryption, and error redaction. The complete
  suite passes with 128 tests.
- Kept the schema disconnected from chat and repository operations; no real
  personal data or runtime database was created.

Next:

- Implement typed repository envelopes, append-only revision writes, entities,
  links, lifecycle transitions, optimistic concurrency, and purge-ledger rules
  using temporary synthetic encrypted databases.
- Confirm Linux compatibility in the eventual batched PR run and Windows before
  distributing a packaged Windows build.

### 2026-08-24 — Encrypted SQLite provider spike

Completed:

- Compared standard SQLite, application-level field encryption, SQLite SEE,
  and SQLCipher; selected SQLCipher Community behind replaceable project-owned
  database and key-provider interfaces.
- Pinned `sqlcipher3` 0.6.2 and verified its bundled SQLCipher 4.12.0 Community
  engine on the current Apple-silicon Mac.
- Added a fail-closed connection boundary requiring an explicit absolute path,
  fresh 256-bit key, audit sink, supported cipher status and major version,
  codec support, FTS5, foreign keys, trusted-schema restrictions, bounded
  timeouts, extension-loading disablement, and restrictive POSIX permissions.
- Proved with temporary synthetic data that the file lacks the plaintext SQLite
  header, ordinary SQLite cannot read it, the correct key reopens it, a wrong
  key fails safely, and substituting ordinary SQLite cannot satisfy the
  encryption requirement.
- Added content-free database-open audit events and verified that audit failure
  prevents key acquisition and database creation.
- Added dependency-pinning, key-lifetime, unsafe-path, error-redaction, and
  connection-cleanup tests. The complete suite passes with 117 tests.
- Added `docs/encrypted-database-spike.md` with the decision evidence,
  limitations, and remaining platform checks. No real key, runtime database,
  recovery passphrase, or personal record was created.

Next:

- Implement the checksummed forward-only migration runner and initial schema
  using temporary encrypted databases and synthetic data.
- Confirm Linux compatibility in the eventual batched PR run and Windows before
  distributing a packaged Windows build.

### 2026-08-24 — Bounded redacted audit writer

Completed:

- Added typed audit components, operations, outcomes, reason codes, UUID
  correlation, bounded durations, and allowlisted metadata without a free-form
  message field.
- Added a replaceable audit-sink protocol and an in-memory test sink.
- Added an explicitly configured JSON Lines writer with restrictive POSIX
  permissions, one-line structured events, a 16 KiB event ceiling, a 1 MiB file
  ceiling, five retained rotations, synchronous disk flush, and symbolic-link
  refusal.
- Added focused tests for validation, injection attempts, size bounds,
  permissions, rotation, retention, unsafe targets, and non-sensitive error
  messages. The complete suite passes with 106 tests.
- Kept the writer disconnected from normal chat; no runtime audit file or
  personal-data store is created by this change.

Next:

- Spike the cross-platform encrypted SQLite and key-provider boundary with
  synthetic data.
- Integrate typed audit events as each model, authorization, database, backup,
  and future tool boundary is enabled or revised.

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
