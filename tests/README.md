# Tests

This folder holds automated checks for the assistant's code.

Tests are added alongside each feature. They use mocks, temporary directories,
and synthetic data; personal information, credentials, live audit logs, and
persistent databases do not belong in fixtures or test output.

The 100,000-record encrypted retrieval benchmark is intentionally excluded from
ordinary GitHub Actions runs to conserve CI usage. Run it explicitly at a
retrieval milestone with:

```bash
RUN_MEMORY_PERFORMANCE=1 uv run --locked --no-sync \
  python -m unittest tests.test_memory_retrieval_performance -v
```

Its fixture is synthetic and temporary. Record median and p95 retrieval time,
records examined and returned, estimated tokens, and database size in
`docs/project-status.md` when using the result as milestone evidence.
