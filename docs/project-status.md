# Project Status

This document is the handoff point between coding sessions. At the end of each session, update the current status, outstanding actions, and session history below.

## Current status

- Module 0 foundation is complete: Git safety rules, project documentation, source layout, virtual environment, project metadata, and a basic runnable package are in place.
- The local permission policy is implemented and covered by automated tests.
- GitHub Actions runs the test suite after each push to `main`.
- Runtime personal data, browser state, secrets, logs, databases, and model files remain excluded from Git.
- The assistant has a replaceable language-model interface and a local Ollama adapter configured for `qwen3:14b`.
- Starting the command-line assistant starts Ollama if needed, preloads the local model, uses an 8K context window, and asks Ollama to unload the model after five idle minutes.
- A minimal local-only chat interface is working. It has no saved conversation memory, tools, browser access, personal-data access, or credential access.

## Outstanding actions

Work through these in order unless project needs change.

- [ ] Define a separate conversation/topic policy for subjects the user wants the assistant to avoid or handle carefully.
- [ ] Centralize shared model and connection settings in one configuration module, while keeping machine-specific overrides out of Git.
- [ ] Add bounded, session-only conversation history so a chat remembers earlier turns only while it remains open.
- [ ] Build a permission-enforcement gateway that uses the policy before any future tool can act.
- [ ] Add tests for the enforcement gateway, including approval and denial paths.
- [ ] Design the SQLite data boundary and migrations before storing personal data.

## Session history

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
