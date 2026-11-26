#!/bin/bash
# Installe kiyoctl : compile l'outil IOKit et prépare l'environnement Python.
set -e
cd "$(dirname "$0")"
clang -O2 -o uvcreq uvcreq.c -framework IOKit -framework CoreFoundation
if [ ! -x .venv/bin/python ]; then
  "${PYTHON:-python3}" -m venv .venv
fi
# (le Python Homebrew de ce Mac a besoin de cette bibliothèque pour pip)
[ -d /opt/homebrew/opt/expat/lib ] && export DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib
.venv/bin/python -m pip install -q numpy
echo "OK. Essayez : ./kiyo list"
