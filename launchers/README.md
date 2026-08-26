# Development launcher

`Personal Assistant.app` is a lightweight macOS launcher for the live checkout.
It does not package Python, dependencies, secrets, or the encrypted database.
The executable resolves this repository relative to the tracked app bundle, or
uses `~/Projects/Local-assistant/personal-assistant` from an installed copy, and
starts the locked `uv` environment without opening Terminal.

Link the bundle into `~/Applications` to make it available to Spotlight and the
Dock. A packaged, relocatable application remains a later release task.
