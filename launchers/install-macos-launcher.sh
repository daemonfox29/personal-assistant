#!/bin/zsh
set -eu

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
    -o "$destination/Contents/MacOS/Personal Assistant"
/bin/cp "$source_dir/Info.plist" "$destination/Contents/Info.plist"
/usr/bin/codesign --force --deep --sign - "$destination"
/usr/bin/mdimport "$destination"
