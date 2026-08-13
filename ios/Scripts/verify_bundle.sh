#!/bin/sh
set -eu

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SOURCE_ROOT="$PROJECT_DIR/../core"
RELEASE_LABEL="2026.08.10.2"
EXPECTED_MARKETING_VERSION="2026.8.10"
EXPECTED_BUILD_VERSION="5"
APP_PATH="${1:-}"
if [ -z "$APP_PATH" ] || [ ! -d "$APP_PATH" ]; then
    echo "Kullanım: $0 /tam/yol/Divan.app" >&2
    exit 2
fi

for required in \
    Info.plist \
    Divan \
    app/server.py \
    app/index.html \
    app/secure_sync_transport.py \
    app/sync_engine.py \
    app/sync_service.py \
    app/sync_qr.py \
    app/qrcodegen.py \
    app/ios_entry.py \
    app/assets/portraits/manifest.json \
    app/assets/portraits/freud.jpg \
    AppIcon60x60@2x.png \
    app_packages/certifi/cacert.pem \
    PrivacyInfo.xcprivacy \
    Frameworks/Python.framework/Python \
    Frameworks/Python.framework/PrivacyInfo.xcprivacy \
    Frameworks/_sqlite3.framework/_sqlite3 \
    Frameworks/_ssl.framework/_ssl \
    Frameworks/_ssl.framework/PrivacyInfo.xcprivacy \
    Frameworks/_hashlib.framework/PrivacyInfo.xcprivacy
do
    if [ ! -e "$APP_PATH/$required" ]; then
        echo "Eksik paket bileşeni: $required" >&2
        exit 1
    fi
done

plutil -lint "$APP_PATH/Info.plist" >/dev/null
file "$APP_PATH/Divan" | grep -q 'arm64'

ACTUAL_MARKETING_VERSION="$(plutil -extract \
    CFBundleShortVersionString raw "$APP_PATH/Info.plist")"
ACTUAL_BUILD_VERSION="$(plutil -extract \
    CFBundleVersion raw "$APP_PATH/Info.plist")"
if [ "$ACTUAL_MARKETING_VERSION" != "$EXPECTED_MARKETING_VERSION" ] || \
        [ "$ACTUAL_BUILD_VERSION" != "$EXPECTED_BUILD_VERSION" ]; then
    echo "Paket sürümü beklenen Divan $RELEASE_LABEL sürümüyle uyuşmuyor: $ACTUAL_MARKETING_VERSION ($ACTUAL_BUILD_VERSION)" >&2
    exit 1
fi

for file in \
    server.py \
    secure_sync_transport.py \
    sync_engine.py \
    sync_service.py \
    sync_qr.py \
    qrcodegen.py \
    index.html
do
    if ! cmp -s "$SOURCE_ROOT/$file" "$APP_PATH/app/$file"; then
        echo "Paket güncel ortak Divan kaynağını içermiyor: $file" >&2
        exit 1
    fi
done

if ! grep -E -q '^BATCH_VERSION[[:space:]]*=[[:space:]]*2[[:space:]]*$' \
        "$APP_PATH/app/sync_engine.py"; then
    echo "Paket cihaz eşitleme protokolü v2'yi içermiyor." >&2
    exit 1
fi

ICON_NAME="$(plutil -extract \
    CFBundleIcons.CFBundlePrimaryIcon.CFBundleIconName raw \
    "$APP_PATH/Info.plist" 2>/dev/null || true)"
if [ "$ICON_NAME" != "AppIcon" ]; then
    echo "Uygulama simgesi Info.plist içinde tanımlı değil." >&2
    exit 1
fi

ICON_BITMAP="$(mktemp "${TMPDIR:-/tmp}/divan-icon.XXXXXX.bmp")"
trap 'rm -f "$ICON_BITMAP"' EXIT HUP INT TERM
sips -s format bmp "$APP_PATH/AppIcon60x60@2x.png" \
    --out "$ICON_BITMAP" >/dev/null
if ! od -An -tu1 -j 54 "$ICON_BITMAP" | awk '
    { for (i = 1; i <= NF; i++) if ($i != 0) found = 1 }
    END { exit(found ? 0 : 1) }
'; then
    echo "Uygulama simgesi tamamen siyah veya boş." >&2
    exit 1
fi

if find "$APP_PATH" -type f \( \
    -name '*.db' -o -name '*.db-*' -o -name '*.sqlite' -o \
    -name '*.sqlite3' \
    \) -print -quit | grep -q .; then
    echo "Paketin içinde kullanıcı veritabanı bulundu." >&2
    exit 1
fi

if [ -d "$APP_PATH/python/lib/python3.13/test" ]; then
    echo "CPython test paketi yanlışlıkla uygulamaya girmiş." >&2
    exit 1
fi

if [ -e "$APP_PATH/app/assets/divan-tanitim-kapak-3248x2014.png" ]; then
    echo "Kullanılmayan tanıtım görseli yanlışlıkla uygulamaya girmiş." >&2
    exit 1
fi

if find "$APP_PATH/Frameworks" -maxdepth 1 -type d \( \
    -name '_test*.framework' -o -name '_ctypes_test.framework' -o \
    -name '_xxtestfuzz.framework' -o -name 'xxlimited*.framework' -o \
    -name 'xxsubtype.framework' \
    \) -print -quit | grep -q .; then
    echo "Test-only Python frameworkü yanlışlıkla uygulamaya girmiş." >&2
    exit 1
fi

if LC_ALL=C grep -R -a -E -q \
    'sk-(proj-)?[A-Za-z0-9_-]{20,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' \
    "$APP_PATH/app" "$APP_PATH/app_packages"; then
    echo "Paket kaynaklarında gizli anahtar benzeri içerik bulundu." >&2
    exit 1
fi

echo "Divan iOS $RELEASE_LABEL paketi doğrulandı: $APP_PATH"
