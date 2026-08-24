#!/bin/sh
set -eu

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SOURCE_ROOT="$PROJECT_DIR/../freud-dev"
RELEASE_LABEL="2026.08.17.5"
EXPECTED_MARKETING_VERSION="2026.8.17"
EXPECTED_BUILD_VERSION="8"
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
    app/assets/imagery/manifest.json \
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

python3 - "$SOURCE_ROOT/assets/imagery" "$APP_PATH/app/assets/imagery" <<'PY'
import hashlib
import json
import pathlib
import sys

source = pathlib.Path(sys.argv[1])
packaged = pathlib.Path(sys.argv[2])
manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
cards = manifest.get("cards")
if manifest.get("card_count") != 24 or not isinstance(cards, list) or len(cards) != 24:
    raise SystemExit("Freud imgeleme manifesti geçersiz.")
names = {"manifest.json"}
for card in cards:
    filename = card.get("file") if isinstance(card, dict) else None
    if not isinstance(filename, str) or pathlib.PurePath(filename).name != filename or not filename.endswith(".webp"):
        raise SystemExit("Freud imgeleme manifestinde geçersiz dosya adı var.")
    names.add(filename)
actual = {path.name for path in packaged.iterdir() if path.is_file()}
if names != actual:
    raise SystemExit("iOS Freud imgeleme destesi tam veya allowlist ile uyumlu değil.")
for name in names:
    source_data = (source / name).read_bytes()
    packaged_data = (packaged / name).read_bytes()
    if source_data != packaged_data:
        raise SystemExit(f"iOS Freud imgeleme dosyası güncel değil: {name}")
    if name != "manifest.json":
        card = next(item for item in cards if item["file"] == name)
        if card.get("bytes") != len(source_data) or card.get("sha256") != hashlib.sha256(source_data).hexdigest():
            raise SystemExit(f"Freud imgeleme kartı manifestle uyuşmuyor: {name}")
PY

if ! grep -E -q '^BATCH_VERSION[[:space:]]*=[[:space:]]*3[[:space:]]*$' \
        "$APP_PATH/app/sync_engine.py"; then
    echo "Paket cihaz eşitleme protokolü v3'ü içermiyor." >&2
    exit 1
fi
for marker in \
    '"adhd_habit": RecordSpec(' \
    '_ADHD_EVENT_SYNC_STATUSES' \
    '_projection_payload_allowed' \
    'DEVICE_LOCAL_CLINICAL_TABLES'
do
    if ! grep -F -q "$marker" "$APP_PATH/app/sync_engine.py"; then
        echo "Paket güvenli ADHD eşitleme projeksiyonunu içermiyor: $marker" >&2
        exit 1
    fi
done

# The iOS shell deliberately reuses the common therapy engine and web UI.
# Guard the release against a successful-looking build made from a stale
# sibling freud-dev tree: both the API and the user-facing workspaces must be
# present in the sealed application bundle.
for marker in \
    'path == "/api/adhd/dashboard"' \
    'path == "/api/adhd/habits"' \
    'path == "/api/adhd/journal"' \
    'path == "/api/schema-path"' \
    'suppressed_safety'
do
    if ! grep -F -q "$marker" "$APP_PATH/app/server.py"; then
        echo "Paket güncel ADHD/Şema terapi motorunu içermiyor: $marker" >&2
        exit 1
    fi
done

for marker in \
    'id="adhdWorkspaceOverlay"' \
    'id="adhdJournalForm"' \
    'id="schemaPathOverlay"' \
    'scheduleReminderNotificationFor'
do
    if ! grep -F -q "$marker" "$APP_PATH/app/index.html"; then
        echo "Paket güncel ADHD/Şema arayüzünü içermiyor: $marker" >&2
        exit 1
    fi
done

if ! strings "$APP_PATH/Divan" | grep -F -q \
        'scheduleReminderNotification'; then
    echo "iOS paketi yerel ADHD hatırlatıcı köprüsünü içermiyor." >&2
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
