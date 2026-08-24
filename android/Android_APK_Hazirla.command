#!/bin/zsh
set -euo pipefail

HERE="${0:A:h}"
cd "$HERE"
VERSION="2026.08.22.14"

# JDK 17 yolu sabit değildir (sürüm klasörü değişir, kurulum yeri makineye
# göre farklıdır). Sırayla: ortamdaki JAVA_HOME → ~/jdks altındaki herhangi
# bir 17 kurulumu → sistemdeki kurulu JDK 17.
if [[ -z "${JAVA_HOME:-}" || ! -x "${JAVA_HOME:-}/bin/javac" ]]; then
  JAVA_HOME=""
  for candidate in "$HOME"/jdks/*/Contents/Home "$HOME"/jdks/*; do
    if [[ -x "$candidate/bin/javac" ]]; then JAVA_HOME="$candidate"; break; fi
  done
  if [[ -z "$JAVA_HOME" ]] && /usr/libexec/java_home -v 17 >/dev/null 2>&1; then
    JAVA_HOME="$(/usr/libexec/java_home -v 17)"
  fi
fi
if [[ -z "$JAVA_HOME" || ! -x "$JAVA_HOME/bin/javac" ]]; then
  echo "HATA: JDK 17 bulunamadı. Kurulum için: brew install --cask temurin@17"
  exit 1
fi
export JAVA_HOME
export GRADLE_USER_HOME="$HERE/.gradle-user"
# İmza anahtar kasası için yerel klasör; varsa ~/.android/debug.keystore
# kopyalanarak aynı imzayla güncelleme yüklenebilir kalır.
export ANDROID_USER_HOME="${ANDROID_USER_HOME:-$HERE/.android-user}"

EXPECTED_KEYSTORE_SHA256="50c474206d3de589e7c75452eeb40ebeb5fb8a4f2d3620b9e4746a279755ed0d"
KEYSTORE="$ANDROID_USER_HOME/debug.keystore"
if [[ ! -f "$KEYSTORE" ]]; then
  echo "HATA: Mevcut Divan imza anahtarı bulunamadı; yeni anahtar üretilmeyecek." >&2
  exit 1
fi
ACTUAL_KEYSTORE_SHA256="$(shasum -a 256 "$KEYSTORE" | awk '{print $1}')"
if [[ "$ACTUAL_KEYSTORE_SHA256" != "$EXPECTED_KEYSTORE_SHA256" ]]; then
  echo "HATA: Divan imza anahtarı beklenen güncelleme anahtarıyla uyuşmuyor." >&2
  exit 1
fi

./gradlew clean verifyDivanEmbedding lintRelease assembleRelease

SOURCE="$HERE/app/build/outputs/apk/release/app-release.apk"
TARGET="$HERE/../Divan-Android-$VERSION.apk"
cp "$SOURCE" "$TARGET"

echo
echo "Divan Android APK hazır:"
echo "$TARGET"
open "$HERE/.."
