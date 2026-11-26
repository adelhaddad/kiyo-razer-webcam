#!/bin/bash
# Installe webcam-pro : environnement Python + modèles d'IA (téléchargés depuis leurs sources officielles).
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-python3.12}"
command -v "$PY" >/dev/null || PY=python3
[ -x .venv/bin/python ] || "$PY" -m venv .venv
# Contournement : certains Python Homebrew ont un module pyexpat cassé (symbole libexpat manquant)
[ -d /opt/homebrew/opt/expat/lib ] && export DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib
.venv/bin/python -m pip install -q -r requirements.txt
# mediapipe / gfpgan installent parfois opencv-python 5 par-dessus : on garde opencv-contrib 4.x (cv2.ximgproc, Haar)
.venv/bin/python -m pip uninstall -q -y opencv-python opencv-contrib-python || true
.venv/bin/python -m pip install -q "opencv-contrib-python<5"
# basicsr (dépendance de GFPGAN) importe un module retiré des torchvision récents
SP=$(.venv/bin/python -c "import site;print(site.getsitepackages()[0])")
sed -i '' 's/torchvision.transforms.functional_tensor/torchvision.transforms.functional/' "$SP/basicsr/data/degradations.py" 2>/dev/null || true

mkdir -p models gfpgan/weights
dl() { [ -s "$2" ] || { echo "Téléchargement $(basename "$2")"; curl -fSL --progress-bar -o "$2" "$1"; }; }
# MediaPipe selfie segmenter (Google, Apache 2.0)
dl https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite models/selfie_segmenter.tflite
# Zero-DCE++ (Li Chongyi et al.) — poids réservés à un usage NON COMMERCIAL
dl "https://raw.githubusercontent.com/Li-Chongyi/Zero-DCE_extension/main/Zero-DCE%2B%2B/snapshots_Zero_DCE%2B%2B/Epoch99.pth" models/zero_dce_pp.pth
# GFPGAN v1.4 (TencentARC) + détection / segmentation de visage (facexlib)
dl https://github.com/TencentARC/GFPGAN/releases/download/v1.3.4/GFPGANv1.4.pth gfpgan/weights/GFPGANv1.4.pth
dl https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth gfpgan/weights/detection_Resnet50_Final.pth
dl https://github.com/xinntao/facexlib/releases/download/v0.2.2/parsing_parsenet.pth gfpgan/weights/parsing_parsenet.pth
echo "OK. Lancez : ./lancer.sh"
