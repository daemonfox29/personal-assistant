#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h:h}"
source_dir="$project_dir/launchers/macos"
destination="$HOME/Applications/Personal Assistant.app"

if [[ -x "$HOME/.local/bin/uv" ]]; then
    uv_path="$HOME/.local/bin/uv"
elif [[ -x "/opt/homebrew/bin/uv" ]]; then
    uv_path="/opt/homebrew/bin/uv"
elif [[ -x "/usr/local/bin/uv" ]]; then
    uv_path="/usr/local/bin/uv"
else
    print -u2 "uv is required to install the Personal Assistant launcher"
    exit 1
fi

"$uv_path" --directory "$project_dir" sync --locked

/bin/mkdir -p "$destination/Contents/MacOS"
/usr/bin/xcrun clang -arch arm64 -Os "$source_dir/launcher.c" \
    -framework Security \
    -o "$destination/Contents/MacOS/Personal Assistant"
/bin/cp "$source_dir/Info.plist" "$destination/Contents/Info.plist"
/usr/bin/codesign --force --deep --sign - "$destination"
launcher="$destination/Contents/MacOS/Personal Assistant"
production_service="$("$launcher" --print-production-service)"
testing_service="$("$launcher" --print-testing-service)"

# The secret travels only between the two Keychain utilities through this pipe.
# `-T ''` removes the creator utility's default ACL entry; the sole trusted
# client is the exact, freshly signed launcher executable.
/usr/bin/security find-generic-password \
    -s "$production_service" -a "primary-memory-key" -w \
    | /usr/bin/awk '{ print; print }' \
    | /usr/bin/security add-generic-password -U \
        -s "$testing_service" -a "primary-memory-key" \
        -T "" -T "$launcher" -w
if ! "$launcher" --verify-testing-credential; then
    print -u2 "The testing Keychain credential could not be restricted to this launcher."
    exit 1
fi
/usr/bin/mdimport "$destination"
