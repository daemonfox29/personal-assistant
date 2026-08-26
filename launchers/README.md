# Development launcher

`install-macos-launcher.sh` builds a tiny native arm64 macOS launcher for the
live checkout. It does not package Python, dependencies, secrets, or the
encrypted database. The executable opens
`~/Projects/Local-assistant/personal-assistant` through the locked `uv`
environment without opening Terminal.

The installer places an ad-hoc-signed bundle in `~/Applications` and asks
Spotlight to index it. A packaged, relocatable application remains a later
release task.
