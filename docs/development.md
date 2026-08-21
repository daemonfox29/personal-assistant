# Development Notes

## Before committing a project-level change

Review `pyproject.toml` whenever a change:

- adds, removes, or changes a Python dependency;
- changes the supported Python version;
- changes package metadata or source layout;
- adds or changes test, formatting, linting, or build tooling.

If `pyproject.toml` changes, update any related documentation and verify the project still installs and tests successfully.
