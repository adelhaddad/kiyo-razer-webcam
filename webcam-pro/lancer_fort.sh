#!/bin/bash
# Lance la webcam "façon smartphone". Options : --doux, --image fichier.jpg, --burst 15 ...
cd "$(dirname "$0")"
[ -d /opt/homebrew/opt/expat/lib ] && export DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib
exec .venv/bin/python webcam_pro_fort.py "$@"
