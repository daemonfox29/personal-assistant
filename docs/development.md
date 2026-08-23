# Development Notes

## Before committing a project-level change

Review `pyproject.toml` whenever a change:

- adds, removes, or changes a Python dependency;
- changes the supported Python version;
- changes package metadata or source layout;
- adds or changes test, formatting, linting, or build tooling.

If `pyproject.toml` changes, update any related documentation and verify the project still installs and tests successfully.

## Change workflow

Develop changes on a branch and open a pull request targeting `main`. GitHub
Actions runs the complete test suite for that pull request. The repository's
`main` protection must require the `Tests / test` check before merging and
prevent direct pushes, so the workflow is an enforced gate rather than an
informational result.

To conserve the current Actions budget, the workflow does not run again after
merge. Post-merge verification can be added later if the risk or budget changes.
