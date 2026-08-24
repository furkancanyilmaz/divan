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
  !/^((server|secure_sync_transport|sync_engine|sync_service|sync_qr|qrcodegen)\.py|index\.html|README\.md|Freud\.command|Guncelle\.command|Testleri\.command|tests\/|tests\/[A-Za-z0-9_.-]+\.py|assets\/|assets\/portraits\/|assets\/portraits\/[A-Za-z0-9_.-]+\.(json|jpe?g|png|webp)|assets\/imagery\/|assets\/imagery\/manifest\.json|assets\/imagery\/[a-z0-9-]+\.webp)$/ {print}
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
if [[ -d assets/imagery ]]; then
  mkdir -p "$BACKUP/assets"
  cp -R assets/imagery "$BACKUP/assets/"
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
[[ -f "$TMP/assets/imagery/manifest.json" ]] || {
  echo "Paket Freud imgeleme manifestini içermiyor."; read; exit 1
}
python3 - "$TMP/assets/imagery" <<'PY'
import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
cards = manifest.get("cards")
if manifest.get("card_count") != 24 or not isinstance(cards, list) or len(cards) != 24:
    raise SystemExit("Freud imgeleme manifesti geçersiz.")
expected = {"manifest.json"}
for card in cards:
    filename = card.get("file") if isinstance(card, dict) else None
    if not isinstance(filename, str) or pathlib.PurePath(filename).name != filename or not filename.endswith(".webp"):
        raise SystemExit("Freud imgeleme manifestinde geçersiz dosya adı var.")
    data = (root / filename).read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise SystemExit("Freud imgeleme kartı WebP değil.")
    if card.get("bytes") != len(data) or card.get("sha256") != hashlib.sha256(data).hexdigest():
        raise SystemExit("Freud imgeleme kartı manifestle uyuşmuyor.")
    expected.add(filename)
actual = {path.name for path in root.iterdir() if path.is_file()}
if expected != actual or any(path.is_symlink() for path in root.iterdir()):
    raise SystemExit("Freud imgeleme destesinde eksik/fazla dosya var.")
PY
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
rm -rf assets/imagery
mkdir -p assets
cp -R "$TMP/assets/imagery" assets/imagery
chmod +x Freud.command Guncelle.command
[[ -f Testleri.command ]] && chmod +x Testleri.command
echo "Güncelleme tamamlandı. Veritabanına dokunulmadı."
echo "Önceki sürüm: $BACKUP"
read
