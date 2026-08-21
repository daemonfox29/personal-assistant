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

Module 0: project foundation and safety setup.

## Safety principles

- The model never receives unrestricted permission to act.
- Credentials are entered manually and are never stored in memory or logs.
- Runtime personal data stays local and is excluded from Git.
