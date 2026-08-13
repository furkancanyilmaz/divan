#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
SOURCE_DIR="${1:-${PROJECT_DIR:h}/core}"
DESTINATION="${2:-${PROJECT_DIR}/.build/Prepared/Divan}"
TEMPORARY="${DESTINATION}.tmp.$$"

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

[[ -d "$SOURCE_DIR" ]] || fail "Divan çekirdek klasörü bulunamadı: $SOURCE_DIR"
for item in "${RUNTIME_FILES[@]}"; do
  [[ -f "${SOURCE_DIR}/${item}" ]] || fail "Çekirdek dosyası eksik: $item"
done
[[ -f "${SOURCE_DIR}/assets/portraits/manifest.json" ]] || \
  fail "Portre manifesti eksik."

if find "${SOURCE_DIR}/assets/portraits" -type f \
    ! -name '*.jpg' ! -name '*.jpeg' ! -name '*.png' ! -name '*.webp' \
    ! -name 'manifest.json' -print -quit | grep -q .; then
  fail "Portre klasöründe izin verilmeyen bir dosya var."
fi
if find "${SOURCE_DIR}/assets/portraits" -type l -print -quit | grep -q .; then
  fail "Portre klasöründe sembolik bağlantı kullanılamaz."
fi
while IFS= read -r portrait; do
  extension="${portrait:e:l}"
  mime="$(/usr/bin/file -b --mime-type "$portrait")"
  case "$extension:$mime" in
    jpg:image/jpeg|jpeg:image/jpeg|png:image/png|webp:image/webp) ;;
    *) fail "Portre dosyasının uzantısı ve içeriği uyuşmuyor: ${portrait:t}" ;;
  esac
done < <(find "${SOURCE_DIR}/assets/portraits" -type f ! -name manifest.json -print)

rm -rf "$TEMPORARY"
mkdir -p "$TEMPORARY/assets"
for item in "${RUNTIME_FILES[@]}"; do
  cp -p "${SOURCE_DIR}/${item}" "${TEMPORARY}/${item}"
done
cp -R "${SOURCE_DIR}/assets/portraits" "${TEMPORARY}/assets/portraits"

if find "$TEMPORARY" -type f \( \
    -name '*.db' -o -name '*.db-*' -o -name '*.sqlite' -o \
    -name '*.sqlite3' -o -name '*.device-id' -o -name '*.pyc' -o \
    -name 'server.log' \) -print -quit | grep -q .; then
  fail "Hazırlanan çekirdekte kullanıcı verisi bulundu."
fi
if find "$TEMPORARY" -type d \( \
    -name yedekler -o -name surum-yedekleri -o -name __pycache__ \
    \) -print -quit | grep -q .; then
  fail "Hazırlanan çekirdekte yedek/önbellek klasörü bulundu."
fi
if rg -n --hidden --glob '*.py' --glob '*.html' --glob '*.json' \
    'sk-(proj-)?[A-Za-z0-9_-]{20,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' \
    "$TEMPORARY" >/dev/null; then
  fail "Hazırlanan çekirdekte API/özel anahtar benzeri içerik bulundu."
fi

mkdir -p "${DESTINATION:h}"
rm -rf "$DESTINATION"
mv "$TEMPORARY" "$DESTINATION"
chmod -R go-rwx "$DESTINATION"
print -- "$DESTINATION"
