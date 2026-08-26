# Module 1.5 Native UI Specification

## Purpose

Module 1.5 makes the assistant usable without routine terminal commands while
preserving the security boundaries completed in Module 1. The first release is
a lean native PySide6 application for one local owner. It is an interface over
the existing Python engine, not a second memory, policy, or execution system.

The command-line interfaces remain recovery and developer fallbacks until the
packaged desktop application has passed macOS and Windows recovery tests.

## Non-negotiable trust boundary

User-entered text, model output, and any future data displayed by the UI are
untrusted. Widgets receive only bounded display values and fixed application-
service methods. They are not passed:

- database connections, SQL, encryption keys, recovery-derived key providers,
  approval authorities, or approval receipts;
- audit sinks or permission-policy objects;
- unrestricted model, filesystem, browser, network, or operating-system
  capabilities; or
- raw exceptions, credentials, passphrases, passcodes, or secret-bearing logs.

The model remains downstream of structured request construction. UI text has
the user role and cannot become system policy. Model output is sanitized and
inserted through code-owned native character formats. A deliberately small
Markdown subset may style headings, lists, bold emphasis, and inline code, but
no model text is interpreted as HTML and it cannot create JavaScript, remote
images, automatic links, or active rich content.

All sensitive or consequential operations continue through the existing
deterministic policy, exact-argument approval, repository, and audit layers.
The UI may request an operation; it cannot authorize itself or downgrade a
policy decision.

The shipped UI implementation is still part of the trusted application code. It
runs in the same Python process, so the narrow public service contract is an
architectural and review boundary, not a security sandbox against malicious UI
code or Python introspection. Third-party UI code, plugins, or remotely supplied
interface components must not be loaded into this process. If future interfaces
need a genuinely different trust level, they require a separately authenticated,
least-authority process and a reviewed IPC protocol.

## Architecture

```text
PySide6 widgets
    |
    | bounded typed calls and display events
    v
AssistantApplicationService
    |
    +-- ConversationService -> model adapter
    +-- MemoryRuntime -> encrypted repository and retrieval
    +-- ConversationHistoryRepository -> encrypted transcript tables
    +-- PasscodeApprovalGate -> exact one-use authorization
    +-- typed audit boundaries
```

`AssistantApplicationService` owns the session lifecycle. It opens memory,
starts the model and optional suggestion worker, serializes chat requests, and
closes background work before clearing the application-owned key provider.
Widgets do not compose these components themselves.

## Initial vertical slice

The first usable slice includes:

1. A first-run setup screen with hidden recovery-passphrase and high-risk-
   passcode fields and local confirmation.
2. Protected automatic unlock after one verified recovery entry, with a recovery
   screen fallback when the machine-local credential is absent or stale. Neither
   path loads the model until encrypted memory unlocks successfully.
3. An explicitly labeled session-only option when memory is not configured.
4. A streaming chat screen with Enter-to-send, Shift+Enter multiline input,
   bounded response-limit selection, one active request at a time, plain-text
   rendering, fixed safe errors, and graceful shutdown.
5. A settings screen that atomically persists bounded context-window, default-
   response, response-ceiling, code-owned system/light/dark theme, installed
   font-family, and font-size values. Version-one preferences migrate to safe
   appearance defaults.
6. An encrypted conversation sidebar with automatic saving, deterministic local
   titles, new-chat and Private Chat controls, reopen-and-continue behavior, and
   confirmed permanent deletion from the live database.
7. Existing explicit-memory phrases and post-response candidate analysis
   through the same trusted runtime used by the CLI.

Memory management, candidate review, backup/restore, and the bounded
audit viewer follow as additional panels over service methods. They must not be
implemented by exposing repository objects to widgets.

## Conversation-history retention amendment

Conversation history is an archive, not persistent memory. Complete transcript
content is stored in dedicated `conversations` and `conversation_messages`
tables inside the existing SQLCipher database. Sidebar list and transcript-load
operations return immutable bounded values through `AssistantApplicationService`;
widgets never receive repository or connection objects.

The user message commits before model generation begins. Assistant content and
fixed notices commit synchronously before the completed event reaches the UI.
Closing the window waits for an active generation worker to finish persistence,
then closes the conversation service and encrypted runtime. Forced process
termination, operating-system failure, or hardware loss cannot be given the same
graceful-shutdown guarantee, but the already-committed user message remains.

Opening a saved conversation restores only complete user/assistant exchanges to
the existing token-bounded RAM context. Notices and unanswered prompts remain
visible but cannot become model roles. Listing other conversations never loads
their content into RAM or model context. Database reads are bounded; very large
archives require future pagination even though the full rows remain stored.

Private Chat stores no transcript, retrieves no persistent memory, intercepts no
explicit-memory command, and produces no automatic memory suggestions. It still
uses bounded in-RAM turns for continuity until a different conversation starts
or the process exits.

Permanent deletion cascades through live transcript rows and emits content-free
audit outcomes. An encrypted backup may retain the deleted rows until that
snapshot expires under normal backup retention; the confirmation dialog states
this limitation. Search, archive, retention timers, and immediate cryptographic
erasure across old snapshots are deferred.

## Resource and responsiveness rules

- Model loading and generation run outside the UI thread.
- Only one chat generation may run per application session.
- Inputs, output accumulation, session history, persistent context, and response
  tokens retain their existing hard bounds.
- Closing the window stops accepting work, waits for active transcript
  finalization, cancels future candidate persistence, closes the memory runtime,
  and releases application-owned key references.
- No hidden retry loop, web server, browser runtime, telemetry, or background
  network service is introduced by the UI.

## Dependency decision

Use `PySide6-Essentials` for the interface and `keyring` for the narrow automatic-
unlock adapter, both pinned and hash-locked through `uv`. Qt Essentials includes
the required QtCore, QtGui, QtWidgets, and QtTest modules without the larger
PySide6 Addons bundle. The credential adapter rejects unknown, null, and
plaintext backends instead of weakening to unprotected storage. New Qt modules
or credential backends require an explicit dependency and security review.

On macOS, the source-run application additionally uses the pinned PyObjC Local
Authentication bridge to require device-owner authentication before the app
reads Keychain. macOS may also accept a paired Apple Watch when that owner-
authentication method is enabled. Apple rejects item-bound access controls for the unsigned
development process, so direct Keychain-item user-presence enforcement must be
verified after `.app` packaging and code signing. Application-level
authentication must not be described as a malware boundary.

Qt is dynamically linked through the official wheels. Distribution must retain
the required LGPL notices and allow replacement of the Qt libraries as required
by the applicable license. Packaged-build licensing verification is a release
gate.

## Acceptance criteria

- Setup, recovery, automatic unlock, and ordinary chat require no terminal
  interaction after launch.
- Secret fields are masked, never echoed into chat, never passed to the model,
  and cleared from widgets immediately after use.
- A failed unlock does not load the model or expose raw errors.
- Missing or stale automatic-unlock credentials fall back to recovery entry and
  never create a replacement database.
- The UI cannot access repository, key-provider, receipt-authority, or audit-sink
  attributes through its public service contract.
- Model output is inserted only as sanitized text with code-owned native
  formatting; model-supplied link syntax remains inert.
- A second simultaneous request is deterministically refused.
- Enter submits a prompt, Shift+Enter remains multiline, and settings survive a
  restart without exceeding the fixed context and response bounds.
- System/light/dark theme, installed-font selection, and bounded global font size
  survive restart without accepting model-authored stylesheets.
- Saved user messages commit before generation; completed assistant output
  commits before the UI reports completion; a graceful close waits for this
  boundary before releasing database keys.
- A saved conversation reopens with structured roles and continues through the
  same bounded context engine. Other sidebar entries consume no model context.
- Private Chat creates no transcript or memory activity.
- Permanent deletion removes live transcript rows, audits no content, and warns
  that encrypted backups retain data until snapshot expiry.
- Window shutdown closes background work and memory before returning.
- UI tests run headlessly and cover secret clearing, busy-state enforcement,
  safe errors, plain-text rendering, and shutdown.
- The full existing test suite and the encrypted retrieval benchmark remain
  within their established limits.

## Deferred release gates

- Native memory-management and backup panels.
- Packaged `.app` creation, code signing, click-to-launch installation, and
  direct `SecAccessControl` user-presence protection on the Keychain item.
- Windows packaging and runtime verification, including its native credential
  backend and recovery fallback.
- Accessibility, keyboard navigation, high-DPI, and screen-reader review.
- A signed update mechanism. The application must not self-update until package
  authenticity and rollback behavior are designed and tested.
