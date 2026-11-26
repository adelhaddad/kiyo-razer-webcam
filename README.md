# kiyo-razer-webcam

**English** | [Français](README.fr.md)

Tools to get more out of a USB webcam on macOS (tested on Apple Silicon, macOS 26).

| Folder | What it does |
|---|---|
| [`webcam-pro/`](webcam-pro) | "Smartphone-style" preview and photos: burst + merge, white balance, tone mapping, background blur (MediaPipe), night mode (Zero-DCE++), AI face restoration (GFPGAN), two cameras side by side |
| [`kiyo-ctl/`](kiyo-ctl) | Controls for the **original Razer Kiyo** (USB `1532:0E03`) without Synapse: focus, exposure, brightness, 50/60 Hz, profiles, automatic re-apply when plugged in |

## Quick start

```bash
git clone https://github.com/adelhaddad/kiyo-razer-webcam.git
cd kiyo-razer-webcam
./kiyo-ctl/installer.sh        # optional, only for a Razer Kiyo
./webcam-pro/installer.sh      # downloads ~540 MB of AI models
./webcam-pro/lancer.sh
```

Requirements: Python 3.10–3.12, Xcode Command Line Tools (`clang`), `ffmpeg` (for `kiyo focus-lock`).
On first launch, allow the Terminal app to use the camera.

## webcam-pro — keys

| Key | Action |
|---|---|
| SPACE | high-quality photo (burst of 10 frames, aligned and merged) |
| F, + / − | background blur on/off, strength |
| L | night mode (Zero-DCE++) |
| G | AI face on photos (GFPGAN, skin color preserved) |
| C / P | before/after comparison / raw image |
| Q | quit |

Options: `--camera N`, `--double`, `--doux` (skin smoothing), `--flou 1.5` (blur strength), `--nuit` (night mode),
`--sans-flou` (no blur), `--sans-visage-ia` (no AI face), `--image file.jpg`.
Photos are saved to `~/Pictures/webcam-pro` (never inside the repository).

Per-camera tuning (white balance strength, night mode on start) lives in `PROFILS` at the top of
[`webcam-pro/webcam_pro.py`](webcam-pro/webcam_pro.py).

## kiyo-ctl

See [`kiyo-ctl/README.md`](kiyo-ctl/README.md). In short: `./kiyo list`, `./kiyo set focus_auto=0 focus=170`,
`./kiyo focus-lock --profil perso`, `./service.sh installer perso`.

## Licenses

- Code in this repository: [MIT](LICENSE).
- Models are **not** included; `installer.sh` downloads them from their official sources:
  - MediaPipe Selfie Segmenter — Google, Apache 2.0
  - Zero-DCE++ — Li Chongyi et al., **non-commercial use only**
  - GFPGAN v1.4 — TencentARC, Apache 2.0 (+ facexlib, MIT)
- `kiyo-ctl` is inspired by [kiyo-control](https://github.com/f0ns/kiyo-control) and [cameractrls](https://github.com/soyersoyer/cameractrls); no code is copied (written from the USB Video Class specification).
- Not affiliated with Razer.

> The scripts, options and console messages are in French.
