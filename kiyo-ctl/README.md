# kiyo-ctl — Razer Kiyo controls for macOS

**English** | [Français](README.fr.md)

Command-line tool for the **original Razer Kiyo** (USB `1532:0E03`), no Synapse needed.
Inspired by [kiyo-control](https://github.com/f0ns/kiyo-control) and [cameractrls](https://github.com/soyersoyer/cameractrls),
which only support the Kiyo Pro / Pro Ultra / V2. Written from the USB Video Class 1.0 specification and
the descriptors read from the camera.

## Install

```bash
./installer.sh
```

## Commands

| Command | Effect |
|---|---|
| `./kiyo info` | USB info (firmware, chip, link speed) |
| `./kiyo list` | every control: value, min, max, default |
| `./kiyo get focus brightness` | read controls |
| `./kiyo set focus_auto=0 focus=177` | set controls (order handled: auto modes first) |
| `./kiyo focus-lock --profil perso` | sweeps the focus, measures image sharpness, locks the sharpest position |
| `./kiyo save perso` / `./kiyo load perso` | save / re-apply a profile (`~/.config/kiyoctl/`) |
| `./kiyo watch perso` | stays running and re-applies the profile on every plug-in or camera reset |
| `./kiyo reset` | restore all defaults |
| `./kiyo xu-dump` | read-only dump of the proprietary Razer / Alpha Imaging units |

`focus-lock` needs to stream video: run it from the **Terminal** app, which has camera permission.

## Available controls

| Control | Range | Notes |
|---|---|---|
| `exposure_auto` | `manuel` (1) / `auto` (8) | the Kiyo rejects the UVC value "2" |
| `exposure` | 3 – 2047 (× 100 µs) | only when `exposure_auto=manuel` |
| `exposure_priority` | 0 / 1 | 1 = may lower the frame rate to brighten |
| `focus_auto` | 0 / 1 | |
| `focus` | 0 – 255 | only when `focus_auto=0` |
| `zoom` | 100 – 140 | 100 = widest field of view |
| `pantilt` | ±36000, ±36000 | only useful when zoomed |
| `brightness`, `contrast`, `saturation`, `sharpness` | 0 – 255 | default 128 |
| `white_balance_auto` / `white_balance` | 0/1 · 2000 – 7500 K | |
| `backlight` | 0 / 1 | backlight compensation |
| `gain` | 0 – 255 | |
| `anti_flicker` | `off` / `50hz` / `60hz` | **50 Hz in Europe**, 60 Hz in North America |

## How it works

- The Kiyo exposes a Camera Terminal (id 1), a Processing Unit (id 3) and two proprietary Extension Units (ids 2 and 6).
- macOS keeps the camera for its own video driver, so libusb is denied without root. `uvcreq.c` goes through
  **IOKit** (`IOUSBInterfaceInterface::ControlRequest` on the VideoControl interface), like CameraController:
  no special permissions required.
- The original Kiyo **does not store** its settings: they are lost when unplugged.
  Profiles are therefore kept on the Mac and re-applied (`load`, `watch`, and when `webcam-pro/lancer.sh` starts).

## Intentionally not done

- **Firmware**: no custom firmware (proprietary Alpha Imaging chip, real risk of bricking the camera).
  Official updates: Razer's tool, **Windows only**.
- **Proprietary units**: `xu-dump` reads them without writing anything. Unit 6 looks like a command mailbox
  (write-only selectors 1, 3, 4, 6; read-only responses 2, 5, 7, 8, 9; selector 10 returns the text "8455",
  probably the AIT8455 chip). Unit 2 gives access to internal memory addresses.
  The protocol behind Synapse's "low light compensation" is undocumented for this model:
  writing blindly to these units could corrupt the camera, so nothing is sent.

## Background service

```bash
./service.sh installer perso   # install: re-applies "perso" on every plug-in, at login,
                               # and whenever the camera resets (checked every 30 s)
./service.sh etat              # status + last log lines (~/Library/Logs/kiyoctl.log)
./service.sh retirer           # uninstall
```

The service is a LaunchAgent (`~/Library/LaunchAgents/com.kiyoctl.watch.plist`).
If this folder lives on an external drive, the service only works while that drive is mounted.
