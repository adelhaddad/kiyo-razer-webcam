# kiyo-ctl — réglages de la Razer Kiyo sous macOS

[English](README.md) | **Français**

Outil en ligne de commande pour la **Razer Kiyo d'origine** (USB `1532:0E03`), sans Synapse.
Inspiré de [kiyo-control](https://github.com/f0ns/kiyo-control) et [cameractrls](https://github.com/soyersoyer/cameractrls),
qui ne gèrent que les Kiyo Pro / Pro Ultra / V2. Écrit à partir de la spécification USB Video Class 1.0 et
des descripteurs lus sur la caméra.

## Installation

```bash
./installer.sh
```

## Commandes

| Commande | Effet |
|---|---|
| `./kiyo info` | infos USB (firmware, puce, vitesse) |
| `./kiyo list` | tous les réglages : valeur, min, max, défaut |
| `./kiyo get focus brightness` | lire des réglages |
| `./kiyo set focus_auto=0 focus=177` | régler (l'ordre est géré : les modes auto d'abord) |
| `./kiyo focus-lock --profil perso` | cherche la meilleure mise au point en mesurant la netteté, puis la verrouille |
| `./kiyo save perso` / `./kiyo load perso` | enregistrer / réappliquer un profil (`~/.config/kiyoctl/`) |
| `./kiyo watch perso` | reste en veille et réapplique le profil à chaque branchement ou si la caméra se réinitialise |
| `./kiyo reset` | tous les réglages par défaut |
| `./kiyo xu-dump` | lecture seule des unités propriétaires Razer / Alpha Imaging |

`focus-lock` a besoin de filmer : lancez-le depuis l'app **Terminal**, qui a l'autorisation caméra.

## Réglages disponibles

| Réglage | Plage | Remarque |
|---|---|---|
| `exposure_auto` | `manuel` (1) / `auto` (8) | la Kiyo refuse la valeur UVC « 2 » |
| `exposure` | 3 – 2047 (× 100 µs) | seulement si `exposure_auto=manuel` |
| `exposure_priority` | 0 / 1 | 1 = peut baisser les images/s pour éclaircir |
| `focus_auto` | 0 / 1 | |
| `focus` | 0 – 255 | seulement si `focus_auto=0` |
| `zoom` | 100 – 140 | 100 = champ le plus large |
| `pantilt` | ±36000, ±36000 | utile seulement en zoom |
| `brightness`, `contrast`, `saturation`, `sharpness` | 0 – 255 | défaut 128 |
| `white_balance_auto` / `white_balance` | 0/1 · 2000 – 7500 K | |
| `backlight` | 0 / 1 | compensation de contre-jour |
| `gain` | 0 – 255 | |
| `anti_flicker` | `off` / `50hz` / `60hz` | **50 Hz en Europe** |

## Comment ça marche

- La Kiyo expose : Camera Terminal (id 1), Processing Unit (id 3), deux Extension Units propriétaires (id 2 et 6).
- macOS garde la caméra pour son pilote vidéo : libusb est refusé sans root. `uvcreq.c` passe par
  **IOKit** (`IOUSBInterfaceInterface::ControlRequest` sur l'interface VideoControl), comme CameraController :
  aucun droit spécial nécessaire.
- La Kiyo d'origine **n'enregistre pas** ses réglages : ils sont perdus au débranchement.
  Les profils sont donc gardés sur le Mac et réappliqués (`load`, `watch`, et au lancement de `webcam-pro/lancer.sh`).

## Ce qui n'est pas fait (volontairement)

- **Firmware** : pas de firmware modifié possible (puce Alpha Imaging propriétaire, risque de rendre la caméra inutilisable).
  Mise à jour officielle : outil Razer, **Windows uniquement**.
- **Unités propriétaires** : `xu-dump` les lit sans rien écrire. L'unité 6 ressemble à une boîte aux lettres
  de commandes (sélecteurs en écriture seule 1, 3, 4, 6 ; réponses en lecture 2, 5, 7, 8, 9 ; le sélecteur 10
  renvoie le texte « 8455 », probablement la puce AIT8455). L'unité 2 donne accès à des adresses mémoire internes.
  Le protocole de la « compensation de faible luminosité » de Synapse n'est pas documenté pour ce modèle :
  écrire à l'aveugle dans ces unités pourrait corrompre la caméra, donc rien n'est envoyé.

## Service automatique

```bash
./service.sh installer perso   # réapplique « perso » à chaque branchement, au démarrage du Mac,
                               # et si la caméra se réinitialise (vérification toutes les 30 s)
./service.sh etat              # état + dernières lignes du journal (~/Library/Logs/kiyoctl.log)
./service.sh retirer           # désinstaller
```

Le service est un LaunchAgent (`~/Library/LaunchAgents/com.kiyoctl.watch.plist`).
Si ce dossier est sur un disque externe, le service attend que le disque soit monté pour fonctionner.
