#!/bin/bash
# Lance la webcam "façon smartphone". Options : --doux, --flou 1.5, --sans-flou, --image fichier.jpg ...
cd "$(dirname "$0")"
# corrige une bibliothèque système manquante du Python Homebrew (nécessaire pour MediaPipe)
[ -d /opt/homebrew/opt/expat/lib ] && export DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib
export PYTORCH_ENABLE_MPS_FALLBACK=1
# applique le profil « perso » de la Razer Kiyo si elle est branchée (mise au point, luminosité, 50 Hz)
[ -x ../kiyo-ctl/kiyo ] && ../kiyo-ctl/kiyo load perso >/dev/null 2>&1
exec .venv/bin/python webcam_pro.py "$@"
