#!/bin/zsh
set -e
cd "$(dirname "$0")"

echo "Divan yerel güncelleyici"
echo "Güncelleme zip dosyasını bu pencereye sürükleyip Enter'a basın:"
read ZIPFILE
ZIPFILE="${ZIPFILE#\'}"; ZIPFILE="${ZIPFILE%\'}"
ZIPFILE="${ZIPFILE#\"}"; ZIPFILE="${ZIPFILE%\"}"

if [[ ! -f "$ZIPFILE" ]]; then
  echo "Dosya bulunamadı."
  read
  exit 1
fi

BAD=$(unzip -Z1 "$ZIPFILE" | awk '
  /^\// || /\.\./ {print; next}
  !/^((server|secure_sync_transport|sync_engine|sync_service|sync_qr|qrcodegen)\.py|index\.html|README\.md|Freud\.command|Guncelle\.command|Testleri\.command|tests\/|tests\/[A-Za-z0-9_.-]+\.py|assets\/|assets\/portraits\/|assets\/portraits\/[A-Za-z0-9_.-]+\.(json|jpe?g|png|webp))$/ {print}
')
if [[ -n "$BAD" ]]; then
  echo "Paket izin verilmeyen dosyalar içeriyor:"
  echo "$BAD"
  read
  exit 1
fi

STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="surum-yedekleri/$STAMP"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$BACKUP"
for f in server.py secure_sync_transport.py sync_engine.py sync_service.py \
  sync_qr.py qrcodegen.py index.html README.md Freud.command Guncelle.command; do
  [[ -f "$f" ]] && cp -p "$f" "$BACKUP/"
done
[[ -f Testleri.command ]] && cp -p Testleri.command "$BACKUP/"
[[ -d tests ]] && cp -R tests "$BACKUP/"
if [[ -d assets/portraits ]]; then
  mkdir -p "$BACKUP/assets"
  cp -R assets/portraits "$BACKUP/assets/"
fi
unzip -q "$ZIPFILE" -d "$TMP"

for f in server.py secure_sync_transport.py sync_engine.py sync_service.py \
  sync_qr.py qrcodegen.py index.html; do
  [[ -f "$TMP/$f" ]] || {
    echo "Paket gerekli dosyayı içermiyor: $f"; read; exit 1
  }
done
PYTHONPYCACHEPREFIX=/tmp/divan-pycache python3 -m py_compile \
  "$TMP/server.py" "$TMP/secure_sync_transport.py" "$TMP/sync_engine.py" \
  "$TMP/sync_service.py" "$TMP/sync_qr.py" "$TMP/qrcodegen.py"
if [[ -f "$TMP/assets/portraits/manifest.json" ]]; then
  python3 -m json.tool "$TMP/assets/portraits/manifest.json" >/dev/null
fi
cp -p "$TMP/server.py" "$TMP/secure_sync_transport.py" \
  "$TMP/sync_engine.py" "$TMP/sync_service.py" "$TMP/sync_qr.py" \
  "$TMP/qrcodegen.py" "$TMP/index.html" .
for f in README.md Freud.command Guncelle.command Testleri.command; do
  [[ -f "$TMP/$f" ]] && cp -p "$TMP/$f" .
done
if [[ -d "$TMP/tests" ]]; then
  mkdir -p tests
  for f in "$TMP"/tests/*.py(N); do
    cp -p "$f" tests/
  done
fi
if [[ -d "$TMP/assets/portraits" ]]; then
  mkdir -p assets/portraits
  for f in "$TMP"/assets/portraits/*(.N); do
    cp -p "$f" assets/portraits/
  done
fi
chmod +x Freud.command Guncelle.command
[[ -f Testleri.command ]] && chmod +x Testleri.command
echo "Güncelleme tamamlandı. Veritabanına dokunulmadı."
echo "Önceki sürüm: $BACKUP"
read
