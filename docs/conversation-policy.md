# Conversation Policy

## Purpose

This policy governs what the assistant says. It is separate from the permission policy, which governs whether the assistant may take an action.

A harmless conversation response must never grant access to files, personal data, credentials, the web, or a browser.

## Current Module 0 policy

- The assistant is conversation-only. It has no web, browser, file, database, credential, or tool capability.
- It responds only after the user enters a prompt. It does not start background tasks or act on its own.
- It is given a response budget and is asked to finish its answer within that budget.
- It retains token-bounded recent conversation context only while the
  command-line app remains open. Closing the app erases that context.
- System, user, and assistant roles remain structurally separate. Text entered
  by a user cannot promote itself into a trusted role by including labels such
  as `System:` or `Assistant:`.
- Model output is sanitized at the terminal boundary. Newlines and tabs remain
  readable, while control characters, invisible formatting characters, and
  variation selectors are exposed as literal Unicode code points.
- The application does not currently impose topic-specific content rules. The selected local model may still have its own behavior or limitations, which the application does not claim to override.

## Future topic decisions

Before adding an application-enforced topic rule, record:

1. the exact topic or behavior covered;
2. whether it is allowed, requires an opt-in, or is denied;
3. the user-facing explanation;
4. automated tests proving the rule; and
5. whether the rule applies only to conversation or also to a future tool/action.

Potential future conversation features, including an opt-in policy for lawful, consenting adult discussion, must be designed separately from browser and tool permissions.

## Relationship to permissions

Conversation policy answers: “What kind of answer should the assistant give?”

Permission policy answers: “May the program perform this action?”

The model cannot change either policy by following an instruction inside a chat message.
