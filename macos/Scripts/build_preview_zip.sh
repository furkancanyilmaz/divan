#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
CORE_SOURCE="${DIVAN_CORE_ROOT:-${PROJECT_DIR:h}/freud-dev}"
ICON_SOURCE="${CORE_SOURCE}/assets/DivanAppIcon-1024.png"
PREPARED_CORE="${PROJECT_DIR}/.build/Prepared/Divan"
STAGE_ROOT="${PROJECT_DIR}/.build/DivanPackage"
APP_PATH="${STAGE_ROOT}/Divan.app"
DIST_DIR="${PROJECT_DIR}/dist"
CORE_VERSION="$(/usr/bin/awk -F'"' '/^VERSION = "/ { print $2; exit }' "${CORE_SOURCE}/server.py")"
[[ -n "$CORE_VERSION" ]] || CORE_VERSION="0.0.0"
VERSION="${DIVAN_NATIVE_VERSION:-2026.08.22.14}"
BUILD_VERSION="${DIVAN_NATIVE_BUILD_VERSION:-2026082214}"
ZIP_PATH="${DIST_DIR}/Divan-macOS-${VERSION}.zip"
CHECKSUM_PATH="${DIST_DIR}/Divan-macOS-${VERSION}-SHA256.txt"

for tool in /usr/bin/swift /usr/bin/codesign /usr/bin/ditto /usr/bin/sips \
  /usr/bin/tiffutil /usr/bin/tiff2icns /usr/bin/plutil \
  /usr/libexec/PlistBuddy; do
  [[ -x "$tool" ]] || {
    print -u2 -- "HATA: Gerekli araç bulunamadı: $tool"
    exit 1
  }
done
[[ -f "$ICON_SOURCE" ]] || {
  print -u2 -- "HATA: Divan uygulama simgesi bulunamadı."
  exit 1
}

"${SCRIPT_DIR}/prepare_core.sh" "$CORE_SOURCE" "$PREPARED_CORE" >/dev/null

mkdir -p "${PROJECT_DIR}/.build/home" "${PROJECT_DIR}/.build/ModuleCache" \
  "${PROJECT_DIR}/.build/cache"
HOME="${PROJECT_DIR}/.build/home" \
CLANG_MODULE_CACHE_PATH="${PROJECT_DIR}/.build/ModuleCache" \
SWIFTPM_PACKAGECACHE_PATH="${PROJECT_DIR}/.build/cache" \
  /usr/bin/swift build --package-path "$PROJECT_DIR" \
    -c release --disable-sandbox
BIN_DIR="$(HOME="${PROJECT_DIR}/.build/home" \
  CLANG_MODULE_CACHE_PATH="${PROJECT_DIR}/.build/ModuleCache" \
  SWIFTPM_PACKAGECACHE_PATH="${PROJECT_DIR}/.build/cache" \
  /usr/bin/swift build --package-path "$PROJECT_DIR" \
    -c release --show-bin-path --disable-sandbox)"
BINARY="${BIN_DIR}/Divan"
[[ -x "$BINARY" ]] || {
  print -u2 -- "HATA: Native çalıştırılabilir dosya üretilemedi."
  exit 1
}

rm -rf "$STAGE_ROOT"
mkdir -p "$APP_PATH/Contents/MacOS" "$APP_PATH/Contents/Resources"
cp -p "$BINARY" "$APP_PATH/Contents/MacOS/Divan"
cp -R "$PREPARED_CORE" "$APP_PATH/Contents/Resources/Divan"

PLIST="$APP_PATH/Contents/Info.plist"
/usr/bin/plutil -create xml1 "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleName string Divan" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string Divan" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string com.furkancanyilmaz.divan.swiftui" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleExecutable string Divan" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundlePackageType string APPL" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string ${VERSION}" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string ${BUILD_VERSION}" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :DivanCoreVersion string ${CORE_VERSION}" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :DivanNativeTherapyVersion string ${VERSION}" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string 13.0" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :NSHighResolutionCapable bool true" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string Divan.icns" "$PLIST"

TIFF_PARTS=()
for size in 16 32 48 128 256 512 1024; do
  tiff_path="${STAGE_ROOT}/Divan-${size}.tiff"
  /usr/bin/sips -z "$size" "$size" "$ICON_SOURCE" \
    -s format tiff --out "$tiff_path" >/dev/null
  TIFF_PARTS+=("$tiff_path")
done
/usr/bin/tiffutil -catnosizecheck "${TIFF_PARTS[@]}" \
  -out "${STAGE_ROOT}/Divan.tiff"
/usr/bin/tiff2icns "${STAGE_ROOT}/Divan.tiff" \
  "$APP_PATH/Contents/Resources/Divan.icns"

xattr -cr "$APP_PATH"
/usr/bin/codesign --force --sign - --timestamp=none "$APP_PATH"
"${SCRIPT_DIR}/verify_package.sh" "$APP_PATH" >/dev/null

mkdir -p "$DIST_DIR"
rm -f "$ZIP_PATH" "$CHECKSUM_PATH"
/usr/bin/ditto -c -k --norsrc --noextattr --noqtn --noacl --keepParent \
  "$APP_PATH" "$ZIP_PATH"
"${SCRIPT_DIR}/verify_package.sh" "$ZIP_PATH" >/dev/null
(
  cd "$DIST_DIR"
  /usr/bin/shasum -a 256 "${ZIP_PATH:t}" >"${CHECKSUM_PATH:t}"
)

print -- "$ZIP_PATH"
print -- "$CHECKSUM_PATH"
