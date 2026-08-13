#!/bin/zsh
set -euo pipefail

HERE="${0:A:h}"
cd "$HERE"
VERSION="2026.08.10.2"

export JAVA_HOME="${JAVA_HOME:-$HOME/jdks/jdk-17.0.18+8/Contents/Home}"
export GRADLE_USER_HOME="$HERE/.gradle-user"

./gradlew clean assembleRelease

SOURCE="$HERE/app/build/outputs/apk/release/app-release.apk"
TARGET="$HERE/../Divan-Android-$VERSION.apk"
cp "$SOURCE" "$TARGET"

echo
echo "Divan Android APK hazır:"
echo "$TARGET"
open "$HERE/.."
