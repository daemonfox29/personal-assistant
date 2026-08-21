# Project Status

This document is the handoff point between coding sessions. At the end of each session, update the current status, outstanding actions, and session history below.

## Current status

- Module 0 foundation is complete: Git safety rules, project documentation, source layout, virtual environment, project metadata, and a basic runnable package are in place.
- The local permission policy is implemented and covered by automated tests.
- GitHub Actions runs the test suite after each push to `main`.
- Runtime personal data, browser state, secrets, logs, databases, and model files remain excluded from Git.

## Outstanding actions

Work through these in order unless project needs change.

- [ ] Build a permission-enforcement gateway that uses the policy before any future tool can act.
- [ ] Add tests for the enforcement gateway, including approval and denial paths.
- [ ] Define a separate conversation/topic policy for subjects the user wants the assistant to avoid or handle carefully.
- [ ] Define a replaceable local-model interface before connecting a model provider.
- [ ] Research and choose an initial Ollama model appropriate for the local Mac.
- [ ] Add the Ollama adapter without granting it direct access to tools, data, or credentials.
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
