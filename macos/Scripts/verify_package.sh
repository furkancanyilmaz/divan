#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
CORE_SOURCE="${DIVAN_CORE_ROOT:-${PROJECT_DIR:h}/freud-dev}"
EXPECTED_VERSION="${DIVAN_NATIVE_VERSION:-2026.08.22.15}"
EXPECTED_BUILD="${DIVAN_NATIVE_BUILD_VERSION:-2026082215}"
TUS_CATALOG_RELATIVE="assets/tus/catalog-v1.json"
EXPECTED_TUS_CATALOG_SHA256="88d868de90435a2cc38e1c41d35c25b20bddbaa6221b412715c4009735a12182"
EXPECTED_TUS_CATALOG_BYTES=3780233
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
# Sızıntı taraması her makinede çalışmalı: `rg` kurulu olmayabilir ve
# eksikliği bu kapıyı sessizce atlatıyordu. `grep -E` her yerde vardır.
if find "$APP_PATH/Contents/Resources/Divan" -type f \
    \( -name '*.py' -o -name '*.html' -o -name '*.json' \) -print0 |
    xargs -0 grep -lE \
      '(^|[^A-Za-z0-9])sk-(proj-)?[A-Za-z0-9_-]{20,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' \
      2>/dev/null | grep -q .; then
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

TUS_CATALOG="$APP_PATH/Contents/Resources/Divan/$TUS_CATALOG_RELATIVE"
[[ -f "$TUS_CATALOG" && ! -L "$TUS_CATALOG" ]] || {
  print -u2 -- "HATA: Metadata-only TUS kataloğu eksik."
  exit 1
}
[[ "$(/usr/bin/stat -f '%Lp' "$TUS_CATALOG")" = "600" ]] || {
  print -u2 -- "HATA: Metadata-only TUS kataloğu yalnız kullanıcıya açık (0600) olmalı."
  exit 1
}

[[ -f "$APP_PATH/Contents/Resources/Divan/runtime-source.sha256" ]] || {
  print -u2 -- "HATA: Dondurulmuş ortak kaynak manifesti eksik."
  exit 1
}

python3 - "$APP_PATH/Contents/Resources/Divan" "$CORE_SOURCE" \
  "$EXPECTED_TUS_CATALOG_SHA256" "$EXPECTED_TUS_CATALOG_BYTES" <<'PY'
import hashlib
import json
import pathlib
import re
import sys

embedded = pathlib.Path(sys.argv[1])
source = pathlib.Path(sys.argv[2])
expected_tus_sha256 = sys.argv[3]
expected_tus_bytes = int(sys.argv[4])
frozen = (
    "server.py", "index.html", "secure_sync_transport.py", "sync_engine.py",
    "sync_service.py", "sync_qr.py", "qrcodegen.py", "macos_keychain.py",
    "assets/tus/catalog-v1.json",
)
critical = {
    "server.py": "e205b2e1efc92575cb99262ea85812e4d986369dc4635193bd9e508d31a4fe7b",
    "index.html": "5f03a514745ea90dedb53507393a05711e9432df67f48182868d18365eefb6ab",
    "sync_engine.py": "39005a82d5d358557e222e7de7a6c3a2284453ecf2a8ad69584a142dafacc512",
    "sync_service.py": "aab750f309884aa84b5c47be106da03459066538a3dd71a76ed6112155f3580c",
    "secure_sync_transport.py": "fef550a2b5d5c7ad27c62cbd679d5fdb07d621544ebc0edd98ac376c4f9dc5f4",
    "assets/tus/catalog-v1.json": expected_tus_sha256,
}
manifest = {}
for line in (embedded / "runtime-source.sha256").read_text(
        encoding="ascii").splitlines():
    match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_./-]+)", line)
    if not match or match.group(2) in manifest:
        raise SystemExit("Dondurulmuş ortak kaynak manifesti geçersiz.")
    manifest[match.group(2)] = match.group(1)
if set(manifest) != set(frozen):
    raise SystemExit("Dondurulmuş ortak kaynak manifesti eksik veya fazla dosya içeriyor.")
for name in frozen:
    packaged = embedded / name
    authoritative = source / name
    if not packaged.is_file() or not authoritative.is_file():
        raise SystemExit(f"Dondurulmuş ortak kaynak eksik: {name}")
    if packaged.read_bytes() != authoritative.read_bytes():
        raise SystemExit(f"Paketlenmiş ortak kaynak güncel değil: {name}")
    digest = hashlib.sha256(packaged.read_bytes()).hexdigest()
    if manifest[name] != digest:
        raise SystemExit(f"Paketlenmiş ortak kaynak manifestle uyuşmuyor: {name}")
    if name in critical and digest != critical[name]:
        raise SystemExit(f"Paketlenmiş ortak kaynak final sürüm değil: {name}")
tus_path = embedded / "assets/tus/catalog-v1.json"
tus_data = tus_path.read_bytes()
if len(tus_data) != expected_tus_bytes:
    raise SystemExit("Paketlenmiş metadata-only TUS kataloğunun boyutu geçersiz.")
try:
    tus_catalog = json.loads(tus_data.decode("utf-8"))
except (UnicodeError, json.JSONDecodeError):
    raise SystemExit("Paketlenmiş metadata-only TUS kataloğu geçerli JSON değil.") from None
if (not isinstance(tus_catalog, dict)
        or tus_catalog.get("protocol") != "divan_tus_catalog_v1"
        or tus_catalog.get("schema_version") != 1):
    raise SystemExit("Paketlenmiş metadata-only TUS katalog protokolü geçersiz.")
if not re.fullmatch(
        r"sha256:[0-9a-f]{64}",
        str(tus_catalog.get("content_fingerprint") or "")):
    raise SystemExit("Paketlenmiş TUS katalog içerik parmak izi geçersiz.")
raw_keys = {
    "answer", "answers", "choice", "choices", "content", "contents",
    "explanation", "explanations", "option", "options", "prompt",
    "question", "questions", "question_text", "raw", "sentence",
    "sentences", "sentence_text", "solution", "solutions", "stem", "text",
}
def contains_raw_key(value):
    if isinstance(value, dict):
        return any(str(key).strip().lower() in raw_keys
                   or contains_raw_key(child) for key, child in value.items())
    if isinstance(value, list):
        return any(contains_raw_key(child) for child in value)
    return False
if contains_raw_key(tus_catalog):
    raise SystemExit("Paketlenmiş TUS kataloğu ham soru/cümle alanı içeriyor.")
sync_text = (embedded / "sync_engine.py").read_text(encoding="utf-8")
match = re.search(r"(?m)^BATCH_VERSION\s*=\s*(\d+)\s*$", sync_text)
if not match or int(match.group(1)) != 8:
    raise SystemExit("Paketlenmiş eşitleme protokolü tam olarak v8 olmalı.")
sync_service_text = (embedded / "sync_service.py").read_text(encoding="utf-8")
sync_required = (
    "clinical_confirmation_required",
    "pending_clinical_confirmation_conv_ids",
    "clinical_safety_pause",
    "clinical_safety_device",
    "clinical_safety_message",
)
if any(marker not in sync_service_text for marker in sync_required):
    raise SystemExit("Paketlenmiş klinik eşitleme v8 güvenlik sözleşmesi eksik.")
sync_transport_text = (embedded / "secure_sync_transport.py").read_text(
    encoding="utf-8")
transport_required = (
    'SYNC_PROTOCOL_VERSION = 8',
    'SYNC_CAPABILITY = "schema_checkpoint_v1"',
    'SCHEMA_PATH_V5_SYNC_CAPABILITY = "schema_path_chat_v5"',
    'SYNC_CAPABILITIES = (',
    'SYNC_PROTOCOL_ERROR_CODE = "sync_protocol_update_required"',
    'Her iki cihazdaki Divan’ı güncelleyin; sonra yeni QR oluşturun.',
)
if any(marker not in sync_transport_text for marker in transport_required):
    raise SystemExit("Paketlenmiş eşitleme v8 / Şema v5 yeteneği eksik.")
server_text = (embedded / "server.py").read_text(encoding="utf-8")
schema = re.search(
    r"(?m)^SCHEMA_PATH_VERSION\s*=\s*(\d+)\s*$", server_text)
if not schema or int(schema.group(1)) != 5:
    raise SystemExit("Paketlenmiş Şema çalışma sözleşmesi tam olarak v5 olmalı.")
required = (
    'SCHEMA_PATH_V5_PROTOCOL = "schema_path_chat_v5"',
    '"next_card": next_card',
    '"message_meta": schema_message_meta_payload(',
    '"interaction_policy": schema_v4_interaction_policy(',
    '"clinical_sync": schema_clinical_sync_public(',
    'def validate_schema_chat_binding(',
    'def validate_schema_v5_chat_binding(',
    'def schema_v5_prompt_delivery(',
    'def schema_v5_next_card(',
    'def schema_v5_plan_for_user_response(',
    'def schema_v5_apply_prompt_completion(',
    '"presentation": "chat_only"',
    '"accept_candidate_chat", "reject_candidate_chat"',
    'schema_binding_result',
    'schema_chat_only_step_data',
    'sync_import_control',
    'sync_import_resume_required',
    'schema_prompt_protocol',
    'schema_prompt_intent',
    'composer_allowed',
    'composer_mode',
    '"composer_surface": "ordinary_chat"',
    '"inline_controls_only": False',
    'source_assistant_message_public_id',
    'meta_event_public_id',
    'clinical_generation',
    'checkpoint_public_id',
    'expected_checkpoint_seq',
)
if any(marker not in server_text for marker in required):
    raise SystemExit("Paketlenmiş Kerem Genç sohbet içi Şema v5 sözleşmesi eksik.")
PY



IMAGERY_DIR="$APP_PATH/Contents/Resources/Divan/assets/imagery"
[[ -f "$IMAGERY_DIR/manifest.json" ]] || {
  print -u2 -- "HATA: Freud imgeleme manifesti eksik."
  exit 1
}
[[ "$(find "$IMAGERY_DIR" -type f -name '*.webp' | wc -l | tr -d ' ')" = "24" ]] || {
  print -u2 -- "HATA: Freud imgeleme destesi 24 kart içermiyor."
  exit 1
}
while IFS= read -r card; do
  [[ "$(/usr/bin/file -b --mime-type "$card")" = "image/webp" ]] || {
    print -u2 -- "HATA: Geçersiz WebP imgeleme kartı: ${card:t}"
    exit 1
  }
done < <(find "$IMAGERY_DIR" -type f -name '*.webp' -print)
python3 - "$IMAGERY_DIR" "$CORE_SOURCE/assets/imagery" <<'PY'
import hashlib
import json
import pathlib
import sys

packaged = pathlib.Path(sys.argv[1])
source = pathlib.Path(sys.argv[2])
manifest = json.loads((packaged / "manifest.json").read_text(encoding="utf-8"))
cards = manifest.get("cards")
if manifest.get("card_count") != 24 or not isinstance(cards, list) or len(cards) != 24:
    raise SystemExit("Freud imgeleme manifesti geçersiz.")
if manifest.get("therapist_allowlist") != ["freud"]:
    raise SystemExit("Freud imgeleme terapist allowlisti geçersiz.")
if manifest.get("presentation_policy") != {
    "descriptions_are_literal": True,
    "psychological_labels": False,
    "max_model_suggestions": 3,
    "suggestions_are_never_selected": True,
    "explicit_user_selection_required": True,
}:
    raise SystemExit("Freud imgeleme sunum politikası geçersiz.")
if manifest.get("visual_policy") != {
    "people_or_faces": False,
    "text_or_logos": False,
    "violence_or_sexuality": False,
    "horror_or_threat": False,
}:
    raise SystemExit("Freud imgeleme görsel güvenlik politikası geçersiz.")
names = {"manifest.json"}
for card in cards:
    filename = card.get("file") if isinstance(card, dict) else None
    if not isinstance(filename, str) or pathlib.PurePath(filename).name != filename:
        raise SystemExit("Freud imgeleme manifestinde geçersiz dosya adı var.")
    names.add(filename)
actual = {path.name for path in packaged.iterdir() if path.is_file()}
if names != actual:
    raise SystemExit("Paketlenmiş Freud imgeleme destesinde allowlist dışı veya eksik dosya var.")
for name in names:
    packaged_data = (packaged / name).read_bytes()
    if packaged_data != (source / name).read_bytes():
        raise SystemExit(f"Paketlenmiş Freud imgeleme dosyası güncel değil: {name}")
    if name != "manifest.json":
        card = next(item for item in cards if item["file"] == name)
        if card.get("bytes") != len(packaged_data) or card.get("sha256") != hashlib.sha256(packaged_data).hexdigest():
            raise SystemExit(f"Freud imgeleme kartı manifestle uyuşmuyor: {name}")
PY

/usr/bin/plutil -lint "$APP_PATH/Contents/Info.plist" >/dev/null
actual_version="$(/usr/libexec/PlistBuddy \
  -c 'Print :CFBundleShortVersionString' \
  "$APP_PATH/Contents/Info.plist" 2>/dev/null || true)"
actual_build="$(/usr/libexec/PlistBuddy \
  -c 'Print :CFBundleVersion' \
  "$APP_PATH/Contents/Info.plist" 2>/dev/null || true)"
therapy_version="$(/usr/libexec/PlistBuddy \
  -c 'Print :DivanNativeTherapyVersion' \
  "$APP_PATH/Contents/Info.plist" 2>/dev/null || true)"
[[ "$actual_version" = "$EXPECTED_VERSION" \
   && "$actual_build" = "$EXPECTED_BUILD" \
   && "$therapy_version" = "$EXPECTED_VERSION" ]] || {
  print -u2 -- "HATA: Paket sürümü ${EXPECTED_VERSION} (${EXPECTED_BUILD}) değil."
  exit 1
}
/usr/bin/codesign --verify --strict --verbose=2 "$APP_PATH"
print -- "Paket doğrulandı: $APP_PATH"
