#!/bin/sh
set -eu

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SOURCE_ROOT="$PROJECT_DIR/../freud-dev"
CONFIG="$PROJECT_DIR/Config/Base.xcconfig"
BRIDGE="$PROJECT_DIR/Divan/Web/DivanNativeBridge.swift"

grep -F -q 'MARKETING_VERSION = 2026.8.17' "$CONFIG"
grep -F -q 'CURRENT_PROJECT_VERSION = 8' "$CONFIG"
grep -E -q '^BATCH_VERSION[[:space:]]*=[[:space:]]*3[[:space:]]*$' \
    "$SOURCE_ROOT/sync_engine.py"
for marker in \
    '"adhd_habit": RecordSpec(' \
    '_ADHD_EVENT_SYNC_STATUSES' \
    '_projection_payload_allowed' \
    'DEVICE_LOCAL_CLINICAL_TABLES'
do
    grep -F -q "$marker" "$SOURCE_ROOT/sync_engine.py"
done

for required in \
    server.py \
    secure_sync_transport.py \
    sync_engine.py \
    sync_service.py \
    sync_qr.py \
    qrcodegen.py \
    index.html
do
    test -f "$SOURCE_ROOT/$required"
done

for marker in \
    'path == "/api/adhd/dashboard"' \
    'path == "/api/adhd/habits"' \
    'path == "/api/adhd/journal"' \
    'path == "/api/schema-path"' \
    'suppressed_safety'
do
    grep -F -q "$marker" "$SOURCE_ROOT/server.py"
done

for marker in \
    'id="adhdWorkspaceOverlay"' \
    'id="adhdJournalForm"' \
    'id="schemaPathOverlay"' \
    'scheduleReminderNotificationFor'
do
    grep -F -q "$marker" "$SOURCE_ROOT/index.html"
done

for marker in \
    '"reminders"' \
    'case "scheduleReminderNotification"' \
    'case "cancelReminderNotification"' \
    'private func scheduleReminderNotification' \
    'private func cancelReminderNotification'
do
    grep -F -q "$marker" "$BRIDGE"
done

sh -n \
    "$PROJECT_DIR/Scripts/prepare_python_bundle.sh" \
    "$PROJECT_DIR/Scripts/verify_bundle.sh" \
    "$PROJECT_DIR/Scripts/package_unsigned_ipa.sh"

echo "Divan iOS 2026.08.17.5 kaynak sözleşmesi doğrulandı."
