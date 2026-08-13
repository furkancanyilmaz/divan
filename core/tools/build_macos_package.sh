#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
ROOT_DIR="${SCRIPT_DIR:h}"
RELEASE_DIR="${ROOT_DIR:h}/releases"
VERSION="2026.08.13.2"
APP_NAME="Divan"
RELEASE_NAME="Divan-macOS-${VERSION}"
BUILD_DIR="${RELEASE_DIR}/.macos-build-${VERSION}"
STAGE_DIR="${BUILD_DIR}/${RELEASE_NAME}"
APP_PATH="${STAGE_DIR}/${APP_NAME}.app"
ZIP_PATH="${RELEASE_DIR}/${RELEASE_NAME}.zip"
CHECKSUM_PATH="${RELEASE_DIR}/${RELEASE_NAME}-SHA256.txt"
SIGNING_IDENTITY="${DIVAN_SIGNING_IDENTITY:--}"
NOTARY_PROFILE="${DIVAN_NOTARY_PROFILE:-}"
ICON_SOURCE="${ROOT_DIR}/assets/DivanAppIcon-1024.png"
LAUNCHER_SOURCE="${SCRIPT_DIR}/macos/DivanLauncher.swift"
README_SOURCE="${SCRIPT_DIR}/macos/OKU_BENI.txt"

RUNTIME_FILES=(
  server.py
  index.html
  secure_sync_transport.py
  sync_engine.py
  sync_service.py
  sync_qr.py
  qrcodegen.py
  macos_keychain.py
)

fail() {
  print -u2 -- "HATA: $*"
  exit 1
}

[[ "$(uname -s)" == "Darwin" ]] || fail "Bu paket yalnız macOS'ta üretilebilir."
for command_path in /usr/bin/xcrun /usr/bin/lipo /usr/bin/tiffutil \
  /usr/bin/tiff2icns /usr/bin/sips /usr/bin/codesign /usr/bin/ditto \
  /usr/libexec/PlistBuddy; do
  [[ -x "$command_path" ]] || fail "Gerekli macOS aracı bulunamadı: $command_path"
done
[[ -f "$ICON_SOURCE" ]] || fail "Uygulama simgesi bulunamadı."
[[ -f "$LAUNCHER_SOURCE" ]] || fail "Mac başlatıcısı bulunamadı."
[[ -f "$README_SOURCE" ]] || fail "Mac kurulum notu bulunamadı."
rg -q '^VERSION = "2026\.08\.11\.3"$' "${ROOT_DIR}/server.py" || \
  fail "server.py sürümü paket sürümüyle eşleşmiyor."

for item in "${RUNTIME_FILES[@]}"; do
  [[ -f "${ROOT_DIR}/${item}" ]] || fail "Çalışma dosyası eksik: $item"
done
[[ -f "${ROOT_DIR}/assets/portraits/manifest.json" ]] || \
  fail "Portre manifesti eksik."

rm -rf "$BUILD_DIR"
mkdir -p "$APP_PATH/Contents/MacOS" "$APP_PATH/Contents/Resources" \
  "$STAGE_DIR" "$RELEASE_DIR"

ARM_LAUNCHER="${BUILD_DIR}/DivanLauncher-arm64"
INTEL_LAUNCHER="${BUILD_DIR}/DivanLauncher-x86_64"
MODULE_CACHE="${BUILD_DIR}/ModuleCache"
mkdir -p "$MODULE_CACHE"
/usr/bin/xcrun swiftc -O -target arm64-apple-macos11.0 \
  -module-cache-path "$MODULE_CACHE" -framework AppKit \
  "$LAUNCHER_SOURCE" -o "$ARM_LAUNCHER"
/usr/bin/xcrun swiftc -O -target x86_64-apple-macos11.0 \
  -module-cache-path "$MODULE_CACHE" -framework AppKit \
  "$LAUNCHER_SOURCE" -o "$INTEL_LAUNCHER"
/usr/bin/lipo -create "$ARM_LAUNCHER" "$INTEL_LAUNCHER" \
  -output "${APP_PATH}/Contents/MacOS/DivanLauncher"
chmod +x "${APP_PATH}/Contents/MacOS/DivanLauncher"

PLIST="${APP_PATH}/Contents/Info.plist"
/usr/bin/plutil -create xml1 "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleName string ${APP_NAME}" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string ${APP_NAME}" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string com.furkancanyilmaz.divan.macos" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleExecutable string DivanLauncher" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundlePackageType string APPL" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleInfoDictionaryVersion string 6.0" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleDevelopmentRegion string tr" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string ${VERSION}" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string 2026081104" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string 11.0" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :NSHighResolutionCapable bool true" "$PLIST"

RESOURCE_DIR="${APP_PATH}/Contents/Resources/Divan"
mkdir -p "${RESOURCE_DIR}/assets"
for item in "${RUNTIME_FILES[@]}"; do
  cp -p "${ROOT_DIR}/${item}" "${RESOURCE_DIR}/${item}"
done
cp -R "${ROOT_DIR}/assets/portraits" "${RESOURCE_DIR}/assets/portraits"

TIFF_PARTS=()
for size in 16 32 48 128 256 512 1024; do
  tiff_path="${BUILD_DIR}/Divan-${size}.tiff"
  /usr/bin/sips -z "$size" "$size" "$ICON_SOURCE" \
    -s format tiff --out "$tiff_path" >/dev/null
  TIFF_PARTS+=("$tiff_path")
done
/usr/bin/tiffutil -catnosizecheck "${TIFF_PARTS[@]}" \
  -out "${BUILD_DIR}/Divan.tiff"
/usr/bin/tiff2icns "${BUILD_DIR}/Divan.tiff" \
  "${APP_PATH}/Contents/Resources/Divan.icns"
/usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string Divan.icns" "$PLIST"

cp -p "$README_SOURCE" "${STAGE_DIR}/OKU_BENI.txt"
ln -s /Applications "${STAGE_DIR}/Applications"
xattr -cr "$STAGE_DIR"
if [[ "$SIGNING_IDENTITY" == "-" ]]; then
  /usr/bin/codesign --force --deep --sign - --timestamp=none "$APP_PATH"
else
  /usr/bin/codesign --force --deep --options runtime --timestamp \
    --sign "$SIGNING_IDENTITY" "$APP_PATH"
fi
/usr/bin/codesign --verify --deep --strict --verbose=2 "$APP_PATH"
/usr/bin/plutil -lint "$PLIST"
/usr/bin/lipo "${APP_PATH}/Contents/MacOS/DivanLauncher" \
  -verify_arch arm64 x86_64

for forbidden in \
  '*.db' '*.db-wal' '*.db-shm' '*.device-id' '*.pyc' '.DS_Store' 'server.log'; do
  if find "$STAGE_DIR" -name "$forbidden" -print -quit | grep -q .; then
    fail "Paket yasaklı bir dosya içeriyor: $forbidden"
  fi
done
if find "$STAGE_DIR" -type d \( -name yedekler -o -name surum-yedekleri \
    -o -name __pycache__ \) -print -quit | grep -q .; then
  fail "Paket veri, yedek veya önbellek klasörü içeriyor."
fi
if rg -n --hidden --glob '*.py' --glob '*.html' \
    'sk-(proj-)?[A-Za-z0-9_-]{20,}' "$RESOURCE_DIR" >/dev/null; then
  fail "Paket kaynaklarında API anahtarına benzeyen bir değer bulundu."
fi

RUNTIME_PATHS=()
for item in "${RUNTIME_FILES[@]}"; do
  [[ "$item" == *.py ]] && RUNTIME_PATHS+=("${RESOURCE_DIR}/${item}")
done
PYTHONPYCACHEPREFIX="${BUILD_DIR}/pycache" python3 -m py_compile \
  "${RUNTIME_PATHS[@]}"
rm -rf "${BUILD_DIR}/pycache"

rm -f "$ZIP_PATH" "$CHECKSUM_PATH"
/usr/bin/ditto -c -k --norsrc --noextattr --noqtn --noacl --keepParent \
  "$STAGE_DIR" "$ZIP_PATH"

if [[ -n "$NOTARY_PROFILE" ]]; then
  [[ "$SIGNING_IDENTITY" != "-" ]] || \
    fail "Noterleme için DIVAN_SIGNING_IDENTITY gerekli."
  /usr/bin/xcrun notarytool submit "$ZIP_PATH" \
    --keychain-profile "$NOTARY_PROFILE" --wait
  /usr/bin/xcrun stapler staple "$APP_PATH"
  /usr/bin/xcrun stapler validate "$APP_PATH"
  rm -f "$ZIP_PATH"
  /usr/bin/ditto -c -k --norsrc --noextattr --noqtn --noacl --keepParent \
    "$STAGE_DIR" "$ZIP_PATH"
fi

(
  cd "$RELEASE_DIR"
  /usr/bin/shasum -a 256 "${ZIP_PATH:t}" >"${CHECKSUM_PATH:t}"
)

print -- "Hazır:"
print -- "$ZIP_PATH"
print -- "$CHECKSUM_PATH"
