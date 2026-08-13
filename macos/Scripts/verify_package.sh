#!/bin/zsh
set -euo pipefail

TARGET="${1:-}"
[[ -n "$TARGET" ]] || {
  print -u2 -- "Kullanım: verify_package.sh Divan.app|paket.zip"
  exit 2
}

TEMPORARY=""
cleanup() {
  [[ -n "$TEMPORARY" ]] && rm -rf "$TEMPORARY"
}
trap cleanup EXIT

if [[ "$TARGET" == *.zip ]]; then
  TEMPORARY="$(mktemp -d "${TMPDIR:-/tmp}/divan-native-verify.XXXXXX")"
  /usr/bin/ditto -x -k "$TARGET" "$TEMPORARY"
  if [[ ! -d "$TEMPORARY/Divan.app" ]] || \
      find "$TEMPORARY" -mindepth 1 -maxdepth 1 ! -name 'Divan.app' -print -quit | grep -q .; then
    print -u2 -- "HATA: ZIP yalnızca tek bir Divan.app içermelidir."
    exit 1
  fi
  APP_PATH="$TEMPORARY/Divan.app"
else
  APP_PATH="$TARGET"
fi

[[ -d "$APP_PATH" ]] || {
  print -u2 -- "HATA: Uygulama bulunamadı."
  exit 1
}
[[ -x "$APP_PATH/Contents/MacOS/Divan" ]] || {
  print -u2 -- "HATA: Native çalıştırılabilir dosya eksik."
  exit 1
}
[[ -f "$APP_PATH/Contents/Resources/Divan/server.py" ]] || {
  print -u2 -- "HATA: Divan çekirdeği eksik."
  exit 1
}
[[ -f "$APP_PATH/Contents/Resources/Divan/macos_keychain.py" ]] || {
  print -u2 -- "HATA: Anahtar Zinciri köprüsü eksik."
  exit 1
}

if find "$APP_PATH" -type l -print -quit | grep -q .; then
  print -u2 -- "HATA: Pakette izin verilmeyen sembolik bağlantı bulundu."
  exit 1
fi

if find "$APP_PATH" -type f \( \
    -name '*.db' -o -name '*.db-*' -o -name '*.sqlite' -o \
    -name '*.sqlite3' -o -name '*.device-id' -o -name '*.pyc' -o \
    -name 'server.log' \) -print -quit | grep -q .; then
  print -u2 -- "HATA: Pakette kullanıcı verisi bulundu."
  exit 1
fi
if find "$APP_PATH" -type d \( \
    -name yedekler -o -name surum-yedekleri -o -name __pycache__ \
    -o -name '.build' \) -print -quit | grep -q .; then
  print -u2 -- "HATA: Pakette yedek/derleme önbelleği bulundu."
  exit 1
fi
if rg -n --hidden --glob '*.py' --glob '*.html' --glob '*.json' \
    'sk-(proj-)?[A-Za-z0-9_-]{20,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' \
    "$APP_PATH/Contents/Resources/Divan" >/dev/null; then
  print -u2 -- "HATA: Pakette API/özel anahtar benzeri içerik bulundu."
  exit 1
fi

PORTRAIT_DIR="$APP_PATH/Contents/Resources/Divan/assets/portraits"
[[ -f "$PORTRAIT_DIR/manifest.json" ]] || {
  print -u2 -- "HATA: Portre manifesti eksik."
  exit 1
}
while IFS= read -r portrait; do
  extension="${portrait:e:l}"
  mime="$(/usr/bin/file -b --mime-type "$portrait")"
  case "$extension:$mime" in
    jpg:image/jpeg|jpeg:image/jpeg|png:image/png|webp:image/webp) ;;
    *)
      print -u2 -- "HATA: Portre dosyasının uzantısı ve içeriği uyuşmuyor: ${portrait:t}"
      exit 1
      ;;
  esac
done < <(find "$PORTRAIT_DIR" -type f ! -name manifest.json -print)

/usr/bin/plutil -lint "$APP_PATH/Contents/Info.plist" >/dev/null
/usr/bin/codesign --verify --strict --verbose=2 "$APP_PATH"
print -- "Paket doğrulandı: $APP_PATH"
