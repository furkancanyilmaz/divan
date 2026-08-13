#!/bin/sh
set -eu

PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
APP_PATH="${1:-}"
OUTPUT_PATH="${2:-$PROJECT_DIR/dist/Divan-iOS-2026.08.10.2-Standalone-Unsigned.ipa}"
case "$OUTPUT_PATH" in
    /*) ;;
    *) OUTPUT_PATH="$(pwd)/$OUTPUT_PATH" ;;
esac
if [ -z "$APP_PATH" ] || [ ! -d "$APP_PATH" ]; then
    echo "Kullanım: $0 /tam/yol/Divan.app [çıktı.ipa]" >&2
    exit 2
fi

"$PROJECT_DIR/Scripts/verify_bundle.sh" "$APP_PATH"
STAGING="${TMPDIR:-/tmp}/divan-ios-package-$$"
trap 'rm -rf "$STAGING"' EXIT INT TERM
mkdir -p "$STAGING/Payload" "$(dirname "$OUTPUT_PATH")"
ditto "$APP_PATH" "$STAGING/Payload/Divan.app"
rm -f "$OUTPUT_PATH"
(
    cd "$STAGING"
    /usr/bin/zip -qry "$OUTPUT_PATH" Payload
)
echo "$OUTPUT_PATH"
