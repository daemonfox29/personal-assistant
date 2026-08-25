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
the user role and cannot become system policy. Model output is rendered as
plain sanitized text: no HTML, JavaScript, remote images, automatic links, or
active rich content.

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
2. A recovery unlock screen that does not load the model until encrypted memory
   has unlocked successfully.
3. An explicitly labeled session-only option when memory is not configured.
4. A streaming chat screen with bounded response-limit selection, one active
   request at a time, plain-text rendering, fixed safe errors, and graceful
   shutdown.
5. Existing explicit-memory phrases and post-response candidate analysis
   through the same trusted runtime used by the CLI.

Memory management, candidate review, backup/restore, settings, and the bounded
audit viewer follow as additional panels over service methods. They must not be
implemented by exposing repository objects to widgets.

## Resource and responsiveness rules

- Model loading and generation run outside the UI thread.
- Only one chat generation may run per application session.
- Inputs, output accumulation, session history, persistent context, and response
  tokens retain their existing hard bounds.
- Closing the window stops accepting work, cancels future candidate persistence,
  closes the memory runtime, and releases application-owned key references.
- No hidden retry loop, web server, browser runtime, telemetry, or background
  network service is introduced by the UI.

## Dependency decision

Use only `PySide6-Essentials`, pinned and hash-locked through `uv`. The Essentials
wheel includes the required QtCore, QtGui, QtWidgets, and QtTest modules without
the larger PySide6 Addons bundle. New Qt modules require an explicit dependency
and security review.

Qt is dynamically linked through the official wheels. Distribution must retain
the required LGPL notices and allow replacement of the Qt libraries as required
by the applicable license. Packaged-build licensing verification is a release
gate.

## Acceptance criteria

- Setup, unlock, and ordinary chat require no terminal interaction after launch.
- Secret fields are masked, never echoed into chat, never passed to the model,
  and cleared from widgets immediately after use.
- A failed unlock does not load the model or expose raw errors.
- The UI cannot access repository, key-provider, receipt-authority, or audit-sink
  attributes through its public service contract.
- Model output is inserted only as plain sanitized text.
- A second simultaneous request is deterministically refused.
- Window shutdown closes background work and memory before returning.
- UI tests run headlessly and cover secret clearing, busy-state enforcement,
  safe errors, plain-text rendering, and shutdown.
- The full existing test suite and the encrypted retrieval benchmark remain
  within their established limits.

## Deferred release gates

- Native memory-management and backup panels.
- Packaged `.app` creation, code signing, and click-to-launch installation.
- Windows packaging and runtime verification.
- Accessibility, keyboard navigation, high-DPI, and screen-reader review.
- A signed update mechanism. The application must not self-update until package
  authenticity and rollback behavior are designed and tested.
