#!/bin/zsh
set -e
cd "$(dirname "$0")"
echo "Divan kalite kontrolü başlıyor…"
PYTHONPYCACHEPREFIX=/tmp/divan-pycache python3 -m unittest discover -s tests -v
echo
echo "Tüm kontroller tamamlandı."
read
