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

Module 0 is complete: a safe local chat foundation with replaceable components.

## Run the local chat

From the project folder:

```bash
./.venv/bin/python -m personal_assistant
```

The app starts Ollama if needed, preloads the local Qwen model, then opens a terminal chat.

- Type `quit` or `exit` to close the app.
- Type `/long <question>` for up to 1,200 response tokens.
- Type `/max <question>` for up to 2,000 response tokens.
- Type `/limit <1-2000> <question>` to choose a custom response budget.

Recent chat turns are kept in RAM only while the app is open. Closing it clears that session context; nothing is saved to a database yet.

The model uses a 400-token normal response budget and an application-wide hard
ceiling of 2,000 response tokens. Commands and future UI settings may choose a
value up to that ceiling, but prompts and model adapters cannot exceed it.

## Settings

Safe shared defaults are in `src/personal_assistant/config.py`.

For a machine-local temporary override, set an environment variable before running the app:

```bash
PERSONAL_ASSISTANT_MODEL_NAME=qwen3:8b ./.venv/bin/python -m personal_assistant
```

The shared default context window is 16,384 tokens. It can be changed
independently of the 2,000-token response ceiling; for example, a machine with
more model capacity can use 32K:

```bash
PERSONAL_ASSISTANT_CONTEXT_TOKENS=32768 ./.venv/bin/python -m personal_assistant
```

Available overrides include:

- `PERSONAL_ASSISTANT_OLLAMA_URL`
- `PERSONAL_ASSISTANT_MODEL_NAME`
- `PERSONAL_ASSISTANT_CONTEXT_TOKENS`
- `PERSONAL_ASSISTANT_RESPONSE_TOKENS`
- `PERSONAL_ASSISTANT_KEEP_ALIVE`
- `PERSONAL_ASSISTANT_HISTORY_CHARACTERS`
- `PERSONAL_ASSISTANT_LONG_RESPONSE_TOKENS`
- `PERSONAL_ASSISTANT_MAX_RESPONSE_TOKENS`

The Ollama URL must be an explicit numeric loopback HTTP address with a port,
such as `http://127.0.0.1:11434` or `http://[::1]:11434`. Hostnames and remote
addresses are rejected. Ollama requests ignore environment proxy settings and
refuse HTTP redirects, so the local adapter cannot be redirected through a
remote service. A future remote-model adapter must be separate and opt-in.

An `.env` file is ignored by Git, but this initial version does not automatically read it. That avoids adding a dependency or accidentally loading secrets before we need them.

## Safety principles

- The model never receives unrestricted permission to act.
- Credentials are entered manually and are never stored in memory or logs.
- Runtime personal data stays local and is excluded from Git.
- The Ollama adapter can connect only to an explicit loopback address.
- Every model request is limited to at most 2,000 response tokens.
- The app currently has no web, browser, file, database, or tool access.
