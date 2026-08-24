#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
SOURCE_APP="${1:-}"
TARGET_APP="${DIVAN_INSTALL_TARGET:-/Applications/Divan.app}"
DATA_DIR="${DIVAN_INSTALL_DATA_DIR:-${HOME}/Library/Application Support/Divan Native Preview}"
PREFERENCES_FILE="${DIVAN_INSTALL_PREFERENCES_FILE:-${HOME}/Library/Preferences/com.furkancanyilmaz.divan.swiftui.plist}"
BACKUP_DIR="${DIVAN_INSTALL_BACKUP_DIR:-${PROJECT_DIR:h}/install-backups}"
STAGED_APP="${TARGET_APP:h}/.Divan.installing.$$.app"
ROLLBACK_APP="${TARGET_APP:h}/.Divan.rollback.$$.app"
SNAPSHOT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/divan-install-state.XXXXXX")"
INSTALL_IN_PROGRESS=0

fail() {
  print -u2 -- "HATA: $*"
  exit 1
}

cleanup() {
  local exit_status="$?"
  set +e
  if [[ "$INSTALL_IN_PROGRESS" = "1" && -d "$ROLLBACK_APP" ]]; then
    rm -rf "$TARGET_APP"
    /bin/mv "$ROLLBACK_APP" "$TARGET_APP"
  fi
  rm -rf "$STAGED_APP" "$SNAPSHOT_DIR"
  return "$exit_status"
}
trap cleanup EXIT

[[ -n "$SOURCE_APP" ]] || \
  fail "Kullanım: install_verified_app.sh /tam/yol/Divan.app"
[[ -d "$SOURCE_APP" ]] || fail "Kurulacak Divan.app bulunamadı."
[[ "${SOURCE_APP:A}" != "${TARGET_APP:A}" ]] || \
  fail "Kaynak ve kurulum hedefi aynı olamaz."
[[ ! -L "$SOURCE_APP" ]] || fail "Kaynak uygulama sembolik bağlantı olamaz."
[[ ! -L "$TARGET_APP" ]] || fail "Kurulum hedefi sembolik bağlantı olamaz."

if /usr/bin/pgrep -x Divan >/dev/null 2>&1; then
  fail "Divan açık. Veriyi sabitlemek için uygulamayı kapatıp yeniden deneyin."
fi

"${SCRIPT_DIR}/verify_package.sh" "$SOURCE_APP" >/dev/null

state_snapshot() {
  local destination="$1"
  local item digest mode size
  : >"$destination"
  for item in \
    "${DATA_DIR}/freud.db" \
    "${DATA_DIR}/freud.db-wal" \
    "${DATA_DIR}/freud.db-shm" \
    "${DATA_DIR}/freud.db.device-id" \
    "$PREFERENCES_FILE"; do
    if [[ -f "$item" ]]; then
      digest="$(/usr/bin/shasum -a 256 "$item" | /usr/bin/awk '{print $1}')"
      mode="$(/usr/bin/stat -f '%Lp' "$item")"
      size="$(/usr/bin/stat -f '%z' "$item")"
      print -r -- "${item}	PRESENT	${digest}	${mode}	${size}" >>"$destination"
    else
      print -r -- "${item}	MISSING" >>"$destination"
    fi
  done
}

state_snapshot "${SNAPSHOT_DIR}/before"

old_version="yok"
old_build="yok"
if [[ -d "$TARGET_APP" ]]; then
  old_version="$(/usr/libexec/PlistBuddy \
    -c 'Print :CFBundleShortVersionString' \
    "$TARGET_APP/Contents/Info.plist" 2>/dev/null || print bilinmiyor)"
  old_build="$(/usr/libexec/PlistBuddy \
    -c 'Print :CFBundleVersion' \
    "$TARGET_APP/Contents/Info.plist" 2>/dev/null || print bilinmiyor)"
  mkdir -p "$BACKUP_DIR"
  backup_app="${BACKUP_DIR}/Divan-${old_version}-build-${old_build}.app"
  if [[ ! -e "$backup_app" ]]; then
    /usr/bin/ditto --norsrc --noextattr --noqtn --noacl \
      "$TARGET_APP" "$backup_app"
    /usr/bin/codesign --verify --strict --verbose=2 "$backup_app" >/dev/null
  else
    /usr/bin/codesign --verify --strict --verbose=2 "$backup_app" >/dev/null || \
      fail "Var olan önceki sürüm yedeği geçersiz; kurulum durduruldu."
  fi
fi

rm -rf "$STAGED_APP" "$ROLLBACK_APP"
/usr/bin/ditto --norsrc --noextattr --noqtn --noacl \
  "$SOURCE_APP" "$STAGED_APP"
"${SCRIPT_DIR}/verify_package.sh" "$STAGED_APP" >/dev/null

if [[ -d "$TARGET_APP" ]]; then
  INSTALL_IN_PROGRESS=1
  /bin/mv "$TARGET_APP" "$ROLLBACK_APP"
fi
if ! /bin/mv "$STAGED_APP" "$TARGET_APP"; then
  [[ ! -d "$ROLLBACK_APP" ]] || /bin/mv "$ROLLBACK_APP" "$TARGET_APP"
  INSTALL_IN_PROGRESS=0
  fail "Yeni uygulama kurulum hedefine taşınamadı."
fi

rollback_install() {
  rm -rf "$TARGET_APP"
  if [[ -d "$ROLLBACK_APP" ]]; then
    /bin/mv "$ROLLBACK_APP" "$TARGET_APP"
  fi
  INSTALL_IN_PROGRESS=0
}

if ! "${SCRIPT_DIR}/verify_package.sh" "$TARGET_APP" >/dev/null; then
  rollback_install
  fail "Kurulan uygulama doğrulanamadı; önceki uygulama geri getirildi."
fi

state_snapshot "${SNAPSHOT_DIR}/after"
if ! /usr/bin/cmp -s "${SNAPSHOT_DIR}/before" "${SNAPSHOT_DIR}/after"; then
  rollback_install
  fail "Kurulum sırasında kullanıcı veri durumu değişti; uygulama geri alındı."
fi

INSTALL_IN_PROGRESS=0
rm -rf "$ROLLBACK_APP"
new_version="$(/usr/libexec/PlistBuddy \
  -c 'Print :CFBundleShortVersionString' \
  "$TARGET_APP/Contents/Info.plist")"
new_build="$(/usr/libexec/PlistBuddy \
  -c 'Print :CFBundleVersion' \
  "$TARGET_APP/Contents/Info.plist")"
print -- "Divan ${new_version} (${new_build}) doğrulanarak kuruldu."
print -- "Kullanıcı verisi ve yerel tercihler değişmedi."
print -- "Önceki sürüm yedeği: ${BACKUP_DIR}/Divan-${old_version}-build-${old_build}.app"
