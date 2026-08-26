#!/bin/zsh
set -eu

project_dir="${0:A:h:h}"
source_dir="$project_dir/launchers/macos"
destination="$HOME/Applications/Personal Assistant.app"

/bin/mkdir -p "$destination/Contents/MacOS"
/usr/bin/xcrun clang -arch arm64 -Os "$source_dir/launcher.c" \
    -o "$destination/Contents/MacOS/Personal Assistant"
/bin/cp "$source_dir/Info.plist" "$destination/Contents/Info.plist"
/usr/bin/codesign --force --deep --sign - "$destination"
/usr/bin/mdimport "$destination"
