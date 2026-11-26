# kiyo-razer-webcam

[English](README.md) | **Français**

Outils pour améliorer une webcam USB sous macOS (testé sur Apple Silicon, macOS 26).

| Dossier | Contenu |
|---|---|
| [`webcam-pro/`](webcam-pro) | Aperçu et photos « façon smartphone » : rafale + fusion, balance des blancs, tone mapping, fond flou (MediaPipe), mode nuit (Zero-DCE++), visage IA (GFPGAN), deux caméras côte à côte |
| [`kiyo-ctl/`](kiyo-ctl) | Réglages de la **Razer Kiyo d'origine** (USB `1532:0E03`) sans Synapse : focus, exposition, luminosité, 50/60 Hz, profils, réapplication automatique au branchement |

## Installation rapide

```bash
git clone https://github.com/adelhaddad/kiyo-razer-webcam.git
cd kiyo-razer-webcam
./kiyo-ctl/installer.sh        # optionnel, seulement pour une Razer Kiyo
./webcam-pro/installer.sh      # télécharge ~540 Mo de modèles d'IA
./webcam-pro/lancer.sh
```

Pré-requis : Python 3.10–3.12, Xcode Command Line Tools (`clang`), `ffmpeg` (pour `kiyo focus-lock`).
Au premier lancement, autorisez l'accès caméra à l'app Terminal.

## webcam-pro — touches

| Touche | Action |
|---|---|
| ESPACE | photo haute qualité (rafale de 10 images alignées et fusionnées) |
| F, + / − | fond flou on/off, intensité |
| L | mode nuit (Zero-DCE++) |
| G | visage IA sur les photos (GFPGAN, couleur de peau préservée) |
| C / P | comparaison avant-après / image brute |
| Q | quitter |

Options : `--camera N`, `--double`, `--doux`, `--flou 1.5`, `--nuit`, `--sans-flou`, `--sans-visage-ia`, `--image fichier.jpg`.
Les photos sont enregistrées dans `~/Pictures/webcam-pro` (jamais dans le dépôt).

## kiyo-ctl

Voir [`kiyo-ctl/README.fr.md`](kiyo-ctl/README.fr.md). En bref : `./kiyo list`, `./kiyo set focus_auto=0 focus=170`,
`./kiyo focus-lock --profil perso`, `./service.sh installer perso`.

## Licences

- Code de ce dépôt : [MIT](LICENSE).
- Les modèles ne sont **pas** inclus ; `installer.sh` les télécharge depuis leurs sources officielles :
  - MediaPipe Selfie Segmenter — Google, Apache 2.0
  - Zero-DCE++ — Li Chongyi et al., **usage non commercial uniquement**
  - GFPGAN v1.4 — TencentARC, Apache 2.0 (+ facexlib, MIT)
- `kiyo-ctl` est inspiré de [kiyo-control](https://github.com/f0ns/kiyo-control) et [cameractrls](https://github.com/soyersoyer/cameractrls) ; aucun code n'en est copié (réécriture depuis la spécification USB Video Class).
- Projet non affilié à Razer.
