#!/bin/zsh
# Freud — Berggasse 19 | çift tıkla başlat
cd "$(dirname "$0")"
PORT="${PORT:-8768}"

# Zaten çalışıyorsa yalnızca tarayıcıyı aç
if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:${PORT}/"; then
  echo "Freud zaten divanda (port ${PORT}) — tarayıcı açılıyor."
  open "http://127.0.0.1:${PORT}"
  exit 0
fi

echo "Freud uyanıyor... (port ${PORT})"
exec python3 server.py
