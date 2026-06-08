#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="PDM"
BUNDLE_ID="com.wenjiazhi.PDM"
MIN_SYSTEM_VERSION="14.0"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MACOS_DIR="$ROOT_DIR/macos"
DIST_DIR="$ROOT_DIR/dist-macos"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_RESOURCES="$APP_CONTENTS/Resources"
APP_BINARY="$APP_MACOS/$APP_NAME"
INFO_PLIST="$APP_CONTENTS/Info.plist"
ARIA2_SOURCE_DIR="$ROOT_DIR/tools/macos/aria2"
APP_ARIA2_DIR="$APP_RESOURCES/aria2"

pkill -x "$APP_NAME" >/dev/null 2>&1 || true

rewrite_homebrew_links() {
  local target="$1"
  local replacement_prefix="$2"
  local lib_dir="$3"

  otool -L "$target" \
    | awk '/\/opt\/homebrew\// {print $1}' \
    | while read -r dependency; do
        local library_name
        library_name="$(basename "$dependency")"
        if [[ -f "$lib_dir/$library_name" ]]; then
          install_name_tool -change "$dependency" "$replacement_prefix/$library_name" "$target" 2>/dev/null || true
        fi
      done
}

copy_bundled_aria2() {
  if [[ ! -x "$ARIA2_SOURCE_DIR/aria2c" ]]; then
    printf 'warning: bundled aria2 source missing: %s\n' "$ARIA2_SOURCE_DIR" >&2
    return
  fi

  rm -rf "$APP_ARIA2_DIR"
  mkdir -p "$APP_ARIA2_DIR"
  ditto "$ARIA2_SOURCE_DIR" "$APP_ARIA2_DIR"
  chmod +x "$APP_ARIA2_DIR/aria2c"

  local lib_dir="$APP_ARIA2_DIR/lib"
  if [[ -d "$lib_dir" ]]; then
    for library in "$lib_dir"/*.dylib; do
      [[ -f "$library" ]] || continue
      install_name_tool -id "@rpath/$(basename "$library")" "$library" 2>/dev/null || true
    done

    rewrite_homebrew_links "$APP_ARIA2_DIR/aria2c" "@executable_path/lib" "$lib_dir"
    for library in "$lib_dir"/*.dylib; do
      [[ -f "$library" ]] || continue
      rewrite_homebrew_links "$library" "@loader_path" "$lib_dir"
    done

    for library in "$lib_dir"/*.dylib; do
      [[ -f "$library" ]] || continue
      codesign --force --sign - "$library"
    done
  fi

  codesign --force --sign - "$APP_ARIA2_DIR/aria2c"
}

swift build --package-path "$MACOS_DIR"
BUILD_BINARY="$(swift build --package-path "$MACOS_DIR" --show-bin-path)/$APP_NAME"

rm -rf "$APP_BUNDLE"
mkdir -p "$APP_MACOS" "$APP_RESOURCES"
cp "$BUILD_BINARY" "$APP_BINARY"
chmod +x "$APP_BINARY"
copy_bundled_aria2

cat >"$INFO_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_ID</string>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSMinimumSystemVersion</key>
  <string>$MIN_SYSTEM_VERSION</string>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
</dict>
</plist>
PLIST

open_app() {
  /usr/bin/open -n "$APP_BUNDLE"
}

case "$MODE" in
  run)
    open_app
    ;;
  --debug|debug)
    lldb -- "$APP_BINARY"
    ;;
  --logs|logs)
    open_app
    /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\""
    ;;
  --telemetry|telemetry)
    open_app
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    open_app
    sleep 1
    pgrep -x "$APP_NAME" >/dev/null
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify]" >&2
    exit 2
    ;;
esac
