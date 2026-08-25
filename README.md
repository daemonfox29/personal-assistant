# Personal Assistant

A modular, local-first personal AI assistant built in Python.

## Initial goals

- Run a local model through Ollama
- Store canonical personal data in SQLite
- Keep model, memory, tools, browser, and interface replaceable
- Require explicit approval before external or sensitive actions
- Keep personal runtime data, browser state, secrets, logs, and databases out of Git
- Begin as a single-agent assistant, with a future path to bounded multi-agent coordination

## Project status

Module 0 and its Module 0.1 hardening gate are complete: a tested local chat
foundation with replaceable components and deterministic safety boundaries.
The Module 1 encrypted persistent-memory implementation is complete behind a
disabled-by-default runtime boundary. It includes redacted auditing, verified
SQLCipher storage, checksummed migrations, typed revisioned records, bounded
retrieval, quarantined suggestions, encrypted recovery, and a bounded chat-
context adapter. Synthetic restart tests pass; portable key onboarding and real
personal data are not enabled yet. Tools are also not enabled.

## Set up the project

The project uses `uv` 0.12.5 for locked, cross-platform dependency management.
After installing that pinned version of
[`uv`](https://docs.astral.sh/uv/getting-started/installation/), run:

```bash
uv sync --locked
```

The committed `uv.lock` records package hashes and compatible SQLCipher wheels
for the supported Python 3.11–3.14 range. Do not edit it manually. `setuptools`
remains the package build backend; `uv` manages resolution, installation,
environments, and project commands.

## Run the local chat

From the project folder:

```bash
uv run --locked python -m personal_assistant
```

The app starts Ollama if needed, sends its documented empty preload request
without evaluating a chat prompt, then opens a terminal chat.

Model output is treated as untrusted terminal text. Control and invisible
formatting characters are displayed as escaped code points instead of being
executed by the terminal. Expected Ollama, model, response, configuration, and
interruption failures produce short user-safe messages without exposing raw
service details.

- Type `quit` or `exit` to close the app.
- Type `/long <question>` for up to 1,200 response tokens.
- Type `/max <question>` for up to 2,000 response tokens.
- Type `/limit <1-2000> <question>` to choose a custom response budget.

Recent chat turns are referenced in application RAM only while the app is open.
Complete turns are evicted from oldest to newest when they exceed the configured
history budget. Closing the app drops the application's references and the app
does not deliberately save this conversation to a file or database. Python,
Ollama, macOS, swap, crash reports, or other system facilities may retain bytes
temporarily; this is not a claim of secure physical memory erasure.

Conversation roles remain structurally separate when sent to the model, so
user text cannot become a trusted system or assistant message. The context
budget conservatively counts the system instruction, current message, recent
turns, message framing, and reserved response space. An individual message
that cannot fit is rejected with a request to shorten it.

The model uses a 400-token normal response budget and an application-wide hard
ceiling of 2,000 response tokens. Commands and future UI settings may choose a
value up to that ceiling, but prompts and model adapters cannot exceed it.

## Settings

Safe shared defaults are in `src/personal_assistant/config.py`.

For a machine-local temporary override, set an environment variable before running the app:

```bash
PERSONAL_ASSISTANT_MODEL_NAME=qwen3:8b uv run --locked python -m personal_assistant
```

The shared default context window is 16,384 tokens. It can be changed
independently of the 2,000-token response ceiling; for example, a machine with
more model capacity can use 32K:

```bash
PERSONAL_ASSISTANT_CONTEXT_TOKENS=32768 uv run --locked python -m personal_assistant
```

Available overrides include:

- `PERSONAL_ASSISTANT_OLLAMA_URL`
- `PERSONAL_ASSISTANT_MODEL_NAME`
- `PERSONAL_ASSISTANT_CONTEXT_TOKENS`
- `PERSONAL_ASSISTANT_RESPONSE_TOKENS`
- `PERSONAL_ASSISTANT_KEEP_ALIVE`
- `PERSONAL_ASSISTANT_HISTORY_TOKENS`
- `PERSONAL_ASSISTANT_LONG_RESPONSE_TOKENS`
- `PERSONAL_ASSISTANT_MAX_RESPONSE_TOKENS`

The Ollama URL must be an explicit numeric loopback HTTP address with a port,
such as `http://127.0.0.1:11434` or `http://[::1]:11434`. Hostnames and remote
addresses are rejected. Ollama requests ignore environment proxy settings and
refuse HTTP redirects, so the local adapter cannot be redirected through a
remote service. A future remote-model adapter must be separate and opt-in.

`.env` variants, private-key containers, credential exports, cookie exports,
token files, password databases, and the local `secrets/` directory are ignored
by Git. The initial version does not automatically read an `.env` file. Ignore
rules reduce accidental commits but are not a secret manager or a substitute
for reviewing staged changes.

## Safety principles

The complete project doctrine and review checklist live in
[`docs/security-principles.md`](docs/security-principles.md). These assumptions
govern future model, memory, browser, tool, data, interface, and audit choices.

- The model never receives unrestricted permission to act.
- Sensitive actions require an opaque, one-use approval receipt bound to the
  exact action and arguments. Receipts expire after at most five minutes and
  can be issued only by the future trusted interface, not by the model.
- Credentials are entered manually and are never stored in memory or logs.
- Runtime personal data stays local and is excluded from Git.
- The Ollama adapter can connect only to an explicit loopback address.
- Every model request is limited to at most 2,000 response tokens.
- The app currently has no web, browser, file, database, or tool access.
