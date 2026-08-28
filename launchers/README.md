# Development launcher

`install-macos-launcher.sh` builds a tiny native arm64 macOS launcher for the
live checkout. It does not package Python, dependencies, secrets, or the
encrypted database. Installation synchronizes the locked editable environment,
then the executable opens its `personal-assistant-ui` entry point directly
without Terminal. Keeping the registered app and Qt window in one process
preserves reliable macOS accessibility and UI-automation discovery. Re-run the
installer after dependency or lockfile changes.

The installer places an ad-hoc-signed bundle in `~/Applications` and asks
Spotlight to index it. A packaged, relocatable application remains a later
release task.
