#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
SOURCE_DIR="${1:-${PROJECT_DIR:h}/freud-dev}"
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
EXPECTED_SERVER_SHA256="e205b2e1efc92575cb99262ea85812e4d986369dc4635193bd9e508d31a4fe7b"
EXPECTED_INDEX_SHA256="9c58ff43ae90febd61c4fe2066fd7ee7649fb232af44bd2a716dc287581672d0"
EXPECTED_SYNC_ENGINE_SHA256="39005a82d5d358557e222e7de7a6c3a2284453ecf2a8ad69584a142dafacc512"
EXPECTED_SYNC_SERVICE_SHA256="aab750f309884aa84b5c47be106da03459066538a3dd71a76ed6112155f3580c"
EXPECTED_SYNC_TRANSPORT_SHA256="fef550a2b5d5c7ad27c62cbd679d5fdb07d621544ebc0edd98ac376c4f9dc5f4"
TUS_CATALOG_RELATIVE="assets/tus/catalog-v1.json"
EXPECTED_TUS_CATALOG_SHA256="88d868de90435a2cc38e1c41d35c25b20bddbaa6221b412715c4009735a12182"
EXPECTED_TUS_CATALOG_BYTES=3780233

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

[[ -f "${SOURCE_DIR}/${TUS_CATALOG_RELATIVE}" \
   && ! -L "${SOURCE_DIR}/${TUS_CATALOG_RELATIVE}" ]] || \
  fail "Metadata-only TUS kataloğu eksik veya sembolik bağlantı."
if find "${SOURCE_DIR}/assets/tus" -mindepth 1 -maxdepth 1 \
    ! -name 'catalog-v1.json' -print -quit | grep -q .; then
  fail "TUS katalog klasöründe allowlist dışı dosya var."
fi
if find "${SOURCE_DIR}/assets/tus" -type l -print -quit | grep -q .; then
  fail "TUS katalog klasöründe sembolik bağlantı kullanılamaz."
fi

python3 - "${SOURCE_DIR}/${TUS_CATALOG_RELATIVE}" \
  "$EXPECTED_TUS_CATALOG_BYTES" <<'PY'
import json
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
expected_bytes = int(sys.argv[2])
data = path.read_bytes()
if len(data) != expected_bytes:
    raise SystemExit("Metadata-only TUS kataloğunun boyutu dondurulmuş sürümle uyuşmuyor.")
try:
    catalog = json.loads(data.decode("utf-8"))
except (UnicodeError, json.JSONDecodeError):
    raise SystemExit("Metadata-only TUS kataloğu geçerli UTF-8 JSON değil.") from None
if not isinstance(catalog, dict) or catalog.get("protocol") != "divan_tus_catalog_v1":
    raise SystemExit("Metadata-only TUS katalog protokolü v1 değil.")
if catalog.get("schema_version") != 1:
    raise SystemExit("Metadata-only TUS katalog şeması v1 değil.")
if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(catalog.get("content_fingerprint") or "")):
    raise SystemExit("Metadata-only TUS katalog içerik parmak izi geçersiz.")
if not all(isinstance(catalog.get(key), list) and catalog[key]
           for key in ("lessons", "question_areas", "reading_areas")):
    raise SystemExit("Metadata-only TUS katalog listeleri eksik.")
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
if contains_raw_key(catalog):
    raise SystemExit("TUS kataloğu ham soru/cümle içeriği alanı içeriyor.")
PY

# Untrusted asset bytes are checked before compatibility metadata. This keeps
# a disguised database/private payload from being hidden behind an unrelated
# protocol error in an otherwise malformed source tree.
python3 - "${SOURCE_DIR}" <<'PY'
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
sync = (root / "sync_engine.py").read_text(encoding="utf-8")
server = (root / "server.py").read_text(encoding="utf-8")
if not re.search(r"(?m)^BATCH_VERSION\s*=\s*8\s*$", sync):
    raise SystemExit("Eşitleme protokolü native sözleşmeyle uyuşmuyor (v8 gerekli).")
if not re.search(r"(?m)^SCHEMA_PATH_VERSION\s*=\s*5\s*$", server):
    raise SystemExit("Şema çalışma sözleşmesi native modellerle uyuşmuyor (v5 gerekli).")
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
if any(marker not in server for marker in required):
    raise SystemExit("Kerem Genç sohbet içi Şema v5 sözleşmesi eksik.")
sync_service = (root / "sync_service.py").read_text(encoding="utf-8")
sync_required = (
    "clinical_confirmation_required",
    "pending_clinical_confirmation_conv_ids",
    "clinical_safety_pause",
    "clinical_safety_device",
    "clinical_safety_message",
)
if any(marker not in sync_service for marker in sync_required):
    raise SystemExit("Klinik eşitleme v8 güvenlik sözleşmesi eksik.")
sync_transport = (root / "secure_sync_transport.py").read_text(encoding="utf-8")
transport_required = (
    'SYNC_PROTOCOL_VERSION = 8',
    'SYNC_CAPABILITY = "schema_checkpoint_v1"',
    'SCHEMA_PATH_V5_SYNC_CAPABILITY = "schema_path_chat_v5"',
    'SYNC_CAPABILITIES = (',
    'SYNC_PROTOCOL_ERROR_CODE = "sync_protocol_update_required"',
    'Her iki cihazdaki Divan’ı güncelleyin; sonra yeni QR oluşturun.',
)
if any(marker not in sync_transport for marker in transport_required):
    raise SystemExit("Eşitleme v8 / Şema v5 yeteneği eksik.")
PY

[[ -f "${SOURCE_DIR}/assets/imagery/manifest.json" ]] || \
  fail "Freud imgeleme manifesti eksik."

if find "${SOURCE_DIR}/assets/imagery" -type f \
    ! -name '*.webp' ! -name 'manifest.json' -print -quit | grep -q .; then
  fail "Freud imgeleme klasöründe izin verilmeyen bir dosya var."
fi
if find "${SOURCE_DIR}/assets/imagery" -type l -print -quit | grep -q .; then
  fail "Freud imgeleme klasöründe sembolik bağlantı kullanılamaz."
fi
imagery_count="$(find "${SOURCE_DIR}/assets/imagery" -type f -name '*.webp' | wc -l | tr -d ' ')"
[[ "$imagery_count" = "24" ]] || fail "Freud imgeleme destesi 24 kart içermeli."
while IFS= read -r card; do
  [[ "$(/usr/bin/file -b --mime-type "$card")" = "image/webp" ]] || \
    fail "Freud imgeleme kartı geçerli WebP değil: ${card:t}"
done < <(find "${SOURCE_DIR}/assets/imagery" -type f -name '*.webp' -print)
python3 - "${SOURCE_DIR}/assets/imagery" <<'PY'
import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
cards = manifest.get("cards")
if manifest.get("card_count") != 24 or not isinstance(cards, list) or len(cards) != 24:
    raise SystemExit("Freud imgeleme manifestindeki kart sayısı geçersiz.")
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
expected = set()
for card in cards:
    filename = card.get("file") if isinstance(card, dict) else None
    if not isinstance(filename, str) or pathlib.PurePath(filename).name != filename or not filename.endswith(".webp"):
        raise SystemExit("Freud imgeleme manifestinde geçersiz dosya adı var.")
    path = root / filename
    data = path.read_bytes()
    if card.get("bytes") != len(data) or card.get("sha256") != hashlib.sha256(data).hexdigest():
        raise SystemExit(f"Freud imgeleme kartı manifestle uyuşmuyor: {filename}")
    expected.add(filename)
actual = {p.name for p in root.glob("*.webp")}
if expected != actual:
    raise SystemExit("Freud imgeleme manifesti ile klasör içeriği uyuşmuyor.")
PY

verify_frozen_hash() {
  local name="$1"
  local expected="$2"
  local actual
  actual="$(/usr/bin/shasum -a 256 "${SOURCE_DIR}/${name}" | /usr/bin/awk '{print $1}')"
  [[ "$actual" = "$expected" ]] || \
    fail "Dondurulmuş ortak kaynak kimliği değişti: ${name}"
}
verify_frozen_hash server.py "$EXPECTED_SERVER_SHA256"
verify_frozen_hash index.html "$EXPECTED_INDEX_SHA256"
verify_frozen_hash sync_engine.py "$EXPECTED_SYNC_ENGINE_SHA256"
verify_frozen_hash sync_service.py "$EXPECTED_SYNC_SERVICE_SHA256"
verify_frozen_hash secure_sync_transport.py "$EXPECTED_SYNC_TRANSPORT_SHA256"
verify_frozen_hash "$TUS_CATALOG_RELATIVE" "$EXPECTED_TUS_CATALOG_SHA256"

rm -rf "$TEMPORARY"
mkdir -p "$TEMPORARY/assets/tus"
for item in "${RUNTIME_FILES[@]}"; do
  cp -p "${SOURCE_DIR}/${item}" "${TEMPORARY}/${item}"
done
cp -R "${SOURCE_DIR}/assets/portraits" "${TEMPORARY}/assets/portraits"
cp -R "${SOURCE_DIR}/assets/imagery" "${TEMPORARY}/assets/imagery"
/usr/bin/install -m 600 "${SOURCE_DIR}/${TUS_CATALOG_RELATIVE}" \
  "${TEMPORARY}/${TUS_CATALOG_RELATIVE}"
(
  cd "$TEMPORARY"
  for item in "${RUNTIME_FILES[@]}"; do
    /usr/bin/shasum -a 256 "$item"
  done
  /usr/bin/shasum -a 256 "$TUS_CATALOG_RELATIVE"
) >"${TEMPORARY}/runtime-source.sha256"

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
# Sızıntı taraması her makinede çalışmalı: `rg` kurulu olmayabilir ve
# eksikliği bu kapıyı sessizce atlatıyordu. `grep -E` her yerde vardır.
if find "$TEMPORARY" -type f \
    \( -name '*.py' -o -name '*.html' -o -name '*.json' \) -print0 |
    xargs -0 grep -lE \
      '(^|[^A-Za-z0-9])sk-(proj-)?[A-Za-z0-9_-]{20,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' \
      2>/dev/null | grep -q .; then
  fail "Hazırlanan çekirdekte API/özel anahtar benzeri içerik bulundu."
fi

mkdir -p "${DESTINATION:h}"
rm -rf "$DESTINATION"
mv "$TEMPORARY" "$DESTINATION"
chmod -R go-rwx "$DESTINATION"
print -- "$DESTINATION"
