#!/usr/bin/env bash
set -euo pipefail

APP_NAME="PDM"
BUNDLE_ID="com.wenjiazhi.PDM"
VERSION="2.2.1"
MIN_SYSTEM_VERSION="14.0"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MACOS_DIR="$ROOT_DIR/macos"
DIST_DIR="$ROOT_DIR/dist-macos"
STAGING_DIR="$DIST_DIR/.staging"
APP_BUNDLE="$STAGING_DIR/$APP_NAME.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_RESOURCES="$APP_CONTENTS/Resources"
APP_BINARY="$APP_MACOS/$APP_NAME"
INFO_PLIST="$APP_CONTENTS/Info.plist"
ARIA2_SOURCE_DIR="$ROOT_DIR/tools/macos/aria2"
APP_ARIA2_DIR="$APP_RESOURCES/aria2"
ICONSET="$DIST_DIR/AppIcon.iconset"
ICNS="$APP_RESOURCES/AppIcon.icns"
DMG_ROOT="$DIST_DIR/.dmg-root"
DMG_PATH="$DIST_DIR/$APP_NAME-macOS.dmg"
INSTALL_TO_APPLICATIONS="${INSTALL_TO_APPLICATIONS:-0}"
INSTALL_APP="/Applications/$APP_NAME.app"

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

rm -rf "$DIST_DIR/$APP_NAME.app" "$STAGING_DIR" "$ICONSET" "$DMG_ROOT" "$DMG_PATH"
mkdir -p "$APP_MACOS" "$APP_RESOURCES" "$DIST_DIR"

swift build --package-path "$MACOS_DIR" -c release
BUILD_BINARY="$(swift build --package-path "$MACOS_DIR" -c release --show-bin-path)/$APP_NAME"
cp "$BUILD_BINARY" "$APP_BINARY"
chmod +x "$APP_BINARY"
copy_bundled_aria2

mkdir -p "$ICONSET"
sips -z 16 16 "$ROOT_DIR/assets/icon.png" --out "$ICONSET/icon_16x16.png" >/dev/null
sips -z 32 32 "$ROOT_DIR/assets/icon.png" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$ROOT_DIR/assets/icon.png" --out "$ICONSET/icon_32x32.png" >/dev/null
sips -z 64 64 "$ROOT_DIR/assets/icon.png" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$ROOT_DIR/assets/icon.png" --out "$ICONSET/icon_128x128.png" >/dev/null
sips -z 256 256 "$ROOT_DIR/assets/icon.png" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$ROOT_DIR/assets/icon.png" --out "$ICONSET/icon_256x256.png" >/dev/null
sips -z 512 512 "$ROOT_DIR/assets/icon.png" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$ROOT_DIR/assets/icon.png" --out "$ICONSET/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$ROOT_DIR/assets/icon.png" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
iconutil -c icns "$ICONSET" -o "$ICNS"

cat >"$INFO_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_ID</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>$VERSION</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSApplicationCategoryType</key>
  <string>public.app-category.utilities</string>
  <key>LSMinimumSystemVersion</key>
  <string>$MIN_SYSTEM_VERSION</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
</dict>
</plist>
PLIST

codesign --force --deep --sign - "$APP_BUNDLE"
codesign --verify --deep --strict "$APP_BUNDLE"
spctl --assess --type execute "$APP_BUNDLE" >/dev/null 2>&1 || true

mkdir -p "$DMG_ROOT"
cp -R "$APP_BUNDLE" "$DMG_ROOT/"
ln -s /Applications "$DMG_ROOT/Applications"

hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$DMG_ROOT" \
  -ov \
  -format UDZO \
  "$DMG_PATH" >/dev/null

hdiutil verify "$DMG_PATH"

if [[ "$INSTALL_TO_APPLICATIONS" == "1" ]]; then
  pkill -x "$APP_NAME" >/dev/null 2>&1 || true
  rm -rf "$INSTALL_APP"
  ditto "$APP_BUNDLE" "$INSTALL_APP"
  xattr -dr com.apple.quarantine "$INSTALL_APP" 2>/dev/null || true
  codesign --verify --deep --strict "$INSTALL_APP"
fi

rm -rf "$DMG_ROOT" "$STAGING_DIR" "$ICONSET"
printf '%s\n' "$DMG_PATH"
