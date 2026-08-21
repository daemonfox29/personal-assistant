# Future Features

Ideas to revisit after the current project step is complete. Add new ideas here as they arise, without needing to interrupt the current work.

## Safer feature scaffolding

Create a small development command that prepares the repetitive parts of adding a new assistant tool or action:

- an action label;
- a permission-policy placeholder;
- a unit-test skeleton;
- a documentation checklist.

The command must not choose a permission level automatically. A person must explicitly decide whether the action is allowed, requires approval, or is denied.

## Policy-completeness checks

Add an automated test that fails when an action label exists without an explicit permission rule and corresponding test coverage.

The current unknown-action fallback remains `DENY` for safety. The completeness check will make an unfinished feature visible during development instead of silently leaving it in that fallback state.

## Future workflow goal

When a feature is added, use automation to create the standard project pieces while requiring a deliberate review of its security policy before the feature is treated as complete.

## Approval interface

After the Module 0.1 approval-receipt foundation is in place, build a small trusted interface that clearly shows the exact action and arguments before the user approves it. Its approval receipt should be one-use and short-lived, so an assistant cannot silently reuse a previous approval for a different action.
