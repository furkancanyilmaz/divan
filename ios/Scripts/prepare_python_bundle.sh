#!/bin/sh
set -eu

SOURCE_ROOT="$PROJECT_DIR/../core"
IOS_PYTHON_ROOT="$PROJECT_DIR/DivanPython"
APP_DESTINATION="$CODESIGNING_FOLDER_PATH/app"
PACKAGES_DESTINATION="$CODESIGNING_FOLDER_PATH/app_packages"

if [ ! -f "$SOURCE_ROOT/server.py" ] || [ ! -f "$SOURCE_ROOT/index.html" ]; then
    echo "Divan ortak kaynakları bulunamadı: $SOURCE_ROOT" >&2
    exit 1
fi

mkdir -p "$APP_DESTINATION" "$PACKAGES_DESTINATION"

rsync -a --delete --delete-excluded \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    "$IOS_PYTHON_ROOT/app_packages/" \
    "$PACKAGES_DESTINATION/"

for file in \
    server.py \
    secure_sync_transport.py \
    sync_engine.py \
    sync_service.py \
    sync_qr.py \
    qrcodegen.py \
    index.html
do
    cp "$SOURCE_ROOT/$file" "$APP_DESTINATION/$file"
done

cp "$IOS_PYTHON_ROOT/ios_entry.py" "$APP_DESTINATION/ios_entry.py"
rsync -a --delete \
    --exclude 'divan-tanitim-kapak-3248x2014.png' \
    "$SOURCE_ROOT/assets/" "$APP_DESTINATION/assets/"

# Fail the Xcode build before the expensive Python framework step if an
# incremental bundle contains stale common code or private local data.
for file in \
    server.py \
    secure_sync_transport.py \
    sync_engine.py \
    sync_service.py \
    sync_qr.py \
    qrcodegen.py \
    index.html
do
    if ! cmp -s "$SOURCE_ROOT/$file" "$APP_DESTINATION/$file"; then
        echo "iOS paket kaynağı güncel ortak kaynakla aynı değil: $file" >&2
        exit 1
    fi
done

if ! grep -E -q '^BATCH_VERSION[[:space:]]*=[[:space:]]*2[[:space:]]*$' \
        "$APP_DESTINATION/sync_engine.py"; then
    echo "iOS paketi cihaz eşitleme protokolü v2'yi içermiyor." >&2
    exit 1
fi

if find "$APP_DESTINATION" "$PACKAGES_DESTINATION" -type f \( \
    -name '*.db' -o -name '*.db-*' -o -name '*.sqlite' -o \
    -name '*.sqlite3' \
    \) -print -quit | grep -q .; then
    echo "iOS paket kaynaklarında kullanıcı veritabanı bulundu." >&2
    exit 1
fi

if find "$APP_DESTINATION" "$PACKAGES_DESTINATION" "$PROJECT_DIR/Divan" \
    -type f \( \
    -name '*.py' -o -name '*.html' -o -name '*.json' -o \
    -name '*.txt' -o -name '*.md' -o -name '*.swift' -o \
    -name '*.m' -o -name '*.h' -o -name '*.plist' -o -name '*.xcprivacy' \
    \) -exec grep -a -E -l \
    'sk-(proj-)?[A-Za-z0-9_-]{20,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' \
    {} + | grep -q .; then
    echo "iOS paket kaynaklarında API/özel anahtar benzeri içerik bulundu." >&2
    exit 1
fi

# BeeWare's official helper installs the target-specific stdlib and turns all
# binary extension modules into signed iOS frameworks.
if [ -z "${EXPANDED_CODE_SIGN_IDENTITY:-}" ]; then
    EXPANDED_CODE_SIGN_IDENTITY="-"
    EXPANDED_CODE_SIGN_IDENTITY_NAME="Ad Hoc"
    export EXPANDED_CODE_SIGN_IDENTITY EXPANDED_CODE_SIGN_IDENTITY_NAME
fi
. "$PROJECT_DIR/Vendor/Python.xcframework/build/utils.sh"
for framework_privacy in \
    "$PROJECT_DIR/Vendor/Python.xcframework/ios-arm64/Python.framework/PrivacyInfo.xcprivacy" \
    "$PROJECT_DIR/Vendor/Python.xcframework/ios-arm64_x86_64-simulator/Python.framework/PrivacyInfo.xcprivacy"
do
    if ! cmp -s "$IOS_PYTHON_ROOT/PythonPrivacyInfo.xcprivacy" \
            "$framework_privacy"; then
        echo "Python.framework gizlilik bildirimi güncel değil." >&2
        exit 1
    fi
done
install_stdlib Vendor/Python.xcframework
PYTHON_VERSION=$(ls -1 "$CODESIGNING_FOLDER_PATH/python/lib" | \
    grep -E '^python3\.[0-9]+$')
DYNLOAD="$CODESIGNING_FOLDER_PATH/python/lib/$PYTHON_VERSION/lib-dynload"
for module in _hashlib _ssl
do
    cp "$IOS_PYTHON_ROOT/ExtensionPrivacyInfo.xcprivacy" \
        "$DYNLOAD/$module.xcprivacy"
done
process_dylibs Vendor/Python.xcframework \
    "python/lib/$PYTHON_VERSION/lib-dynload"
process_dylibs Vendor/Python.xcframework app
process_dylibs Vendor/Python.xcframework app_packages

# CPython's support archive also contains its own regression suite and test-only
# extension modules. They are useful while building Python, but not at Divan
# runtime; removing them keeps the phone bundle smaller and avoids packaging
# sample certificates/private keys from CPython's tests.
STDLIB="$CODESIGNING_FOLDER_PATH/python/lib/python3.13"
rm -rf \
    "$STDLIB/test" \
    "$STDLIB/ensurepip" \
    "$STDLIB/idlelib" \
    "$STDLIB/tkinter" \
    "$STDLIB/turtledemo"
rm -f "$STDLIB/turtle.py"

for module in \
    _ctypes_test \
    _testbuffer \
    _testcapi \
    _testclinic \
    _testclinic_limited \
    _testexternalinspection \
    _testimportmultiple \
    _testinternalcapi \
    _testlimitedcapi \
    _testmultiphase \
    _testsinglephase \
    _xxtestfuzz \
    xxlimited \
    xxlimited_35 \
    xxsubtype
do
    rm -rf "$CODESIGNING_FOLDER_PATH/Frameworks/$module.framework"
    rm -f "$STDLIB/lib-dynload/$module".*.fwork
done
