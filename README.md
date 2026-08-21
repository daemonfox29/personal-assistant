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

## Settings

Safe shared defaults are in `src/personal_assistant/config.py`.

For a machine-local temporary override, set an environment variable before running the app:

```bash
PERSONAL_ASSISTANT_MODEL_NAME=qwen3:8b ./.venv/bin/python -m personal_assistant
```

Available overrides include:

- `PERSONAL_ASSISTANT_MODEL_NAME`
- `PERSONAL_ASSISTANT_CONTEXT_TOKENS`
- `PERSONAL_ASSISTANT_RESPONSE_TOKENS`
- `PERSONAL_ASSISTANT_KEEP_ALIVE`
- `PERSONAL_ASSISTANT_HISTORY_CHARACTERS`
- `PERSONAL_ASSISTANT_LONG_RESPONSE_TOKENS`
- `PERSONAL_ASSISTANT_MAX_RESPONSE_TOKENS`

An `.env` file is ignored by Git, but this initial version does not automatically read it. That avoids adding a dependency or accidentally loading secrets before we need them.

## Safety principles

- The model never receives unrestricted permission to act.
- Credentials are entered manually and are never stored in memory or logs.
- Runtime personal data stays local and is excluded from Git.
- The app currently has no web, browser, file, database, or tool access.
