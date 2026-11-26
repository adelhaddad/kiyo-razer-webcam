#!/usr/bin/env python3
"""
kiyoctl — contrôle de la Razer Kiyo (modèle d'origine, USB 1532:0E03) sous macOS.

Inspiré de kiyo-control (f0ns) et cameractrls (soyersoyer), réécrit depuis la
spécification USB Video Class 1.0 : les réglages passent par des requêtes de
contrôle USB (endpoint 0), sans pilote ni Synapse.

Commandes :
  kiyoctl.py info                      infos USB + unités UVC de la caméra
  kiyoctl.py list                      tous les réglages : valeur, min, max, défaut
  kiyoctl.py get  focus_auto           lire un réglage
  kiyoctl.py set  focus_auto=0 focus=40 exposure_auto=auto
  kiyoctl.py reset                     remettre tous les réglages par défaut
  kiyoctl.py save  mon-profil          enregistrer les réglages actuels (profil JSON)
  kiyoctl.py load  mon-profil          réappliquer un profil
  kiyoctl.py profiles                  lister les profils
  kiyoctl.py watch mon-profil          rester en veille et réappliquer le profil
                                       à chaque branchement / réveil du Mac
  kiyoctl.py xu-dump                   lire (sans rien écrire) les unités Razer/AIT

La Kiyo d'origine ne garde pas ses réglages quand on la débranche :
c'est le Mac qui les mémorise (profils) et les réapplique (watch).
"""
import argparse
import json
import os
import sys
import time

import subprocess

VID, PID = 0x1532, 0x0E03
PROFILE_DIR = os.path.expanduser("~/.config/kiyoctl")

# requêtes UVC
SET_CUR = 0x01
GET_CUR, GET_MIN, GET_MAX, GET_RES, GET_LEN, GET_INFO, GET_DEF = 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87

# Unités de la Kiyo (lues dans ses descripteurs, cf. `kiyoctl.py info`)
VC_INTERFACE = 0
CT, PU = 1, 3            # Camera Terminal, Processing Unit
XU_UNITS = (2, 6)        # extension units propriétaires (Alpha Imaging / Razer)

# nom -> (unité, sélecteur, taille en octets, signé, description, valeurs nommées)
# la Kiyo n'accepte que 1 (manuel) et 8 (auto, « priorité ouverture » en UVC)
AE_MODES = {"manuel": 1, "auto": 8, "priorite-ouverture": 8}
CONTROLS = {
    "exposure_auto":     (CT, 0x02, 1, False, "exposition : manuel / auto", AE_MODES),
    "exposure_priority": (CT, 0x03, 1, False, "0 = cadence fixe, 1 = peut baisser les i/s pour exposer", None),
    "exposure":          (CT, 0x04, 4, False, "temps d'exposition (unités de 100 µs), si exposition manuelle", None),
    "focus":             (CT, 0x06, 2, False, "mise au point (si autofocus coupé)", None),
    "focus_auto":        (CT, 0x08, 1, False, "autofocus 1 = actif, 0 = coupé", None),
    "zoom":              (CT, 0x0B, 2, False, "zoom (minimum = champ le plus large)", None),
    "pantilt":           (CT, 0x0D, 8, False, "pan/tilt (2 × 4 octets, utile seulement si zoomé)", None),
    "brightness":        (PU, 0x02, 2, True,  "luminosité", None),
    "contrast":          (PU, 0x03, 2, False, "contraste", None),
    "saturation":        (PU, 0x07, 2, False, "saturation", None),
    "sharpness":         (PU, 0x08, 2, False, "netteté", None),
    "white_balance":     (PU, 0x0A, 2, False, "balance des blancs en Kelvin (si auto coupé)", None),
    "white_balance_auto": (PU, 0x0B, 1, False, "balance des blancs auto 1 = actif, 0 = coupé", None),
    "backlight":         (PU, 0x01, 2, False, "compensation de contre-jour", None),
    "gain":              (PU, 0x04, 2, False, "gain (amplification du capteur)", None),
    "anti_flicker":      (PU, 0x05, 1, False, "anti-scintillement 0 = off, 1 = 50 Hz (Europe), 2 = 60 Hz",
                          {"off": 0, "50hz": 1, "60hz": 2}),
}
# ordre d'application : les modes "auto" d'abord, sinon les valeurs manuelles sont refusées
APPLY_ORDER = ["exposure_auto", "exposure_priority", "focus_auto", "white_balance_auto", "anti_flicker",
               "exposure", "focus", "white_balance", "zoom", "pantilt", "brightness", "contrast",
               "saturation", "sharpness", "backlight", "gain"]
# réglages qui ne s'appliquent qu'en mode manuel
MANUAL_ONLY = {"exposure": ("exposure_auto", 1), "focus": ("focus_auto", 0),
               "white_balance": ("white_balance_auto", 0)}


class KiyoError(Exception):
    pass


class USBError(KiyoError):
    """La caméra a refusé une requête (réglage non supporté ou valeur invalide)."""


HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uvcreq")


def kiyo_present():
    out = subprocess.run(["ioreg", "-p", "IOUSB", "-l", "-w0"], capture_output=True, text=True).stdout
    return '"idProduct" = %d' % PID in out and '"idVendor" = %d' % VID in out


class Kiyo:
    """Parle à la caméra via `uvcreq` (IOKit), comme CameraController : pas besoin d'être root."""

    def __init__(self):
        if not os.path.exists(HELPER):
            raise KiyoError(f"outil {HELPER} manquant : lancez ./installer.sh")
        self.proc = subprocess.Popen([HELPER, f"{VID:04x}", f"{PID:04x}"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True, bufsize=1)
        first = self.proc.stdout.readline().strip()
        if not first.startswith("READY"):
            self.close()
            raise KiyoError("Razer Kiyo (1532:0E03) introuvable. Est-elle branchée ?")
        self.dev_info = {"bcdDevice": None}

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=2)

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    def _request(self, rtype, req, value, index, length, data=b""):
        self.proc.stdin.write(f"{rtype:x} {req:x} {value:x} {index:x} {length:x} {data.hex()}\n")
        self.proc.stdin.flush()
        ans = self.proc.stdout.readline().strip()
        if not ans.startswith("OK"):
            raise USBError(ans or "pas de réponse")
        return bytes.fromhex(ans[3:]) if len(ans) > 3 else b""

    # -- requêtes bas niveau
    def _get(self, unit, selector, request, length):
        return self._request(0xA1, request, selector << 8, (unit << 8) | VC_INTERFACE, length)

    def _set(self, unit, selector, data):
        self._request(0x21, SET_CUR, selector << 8, (unit << 8) | VC_INTERFACE, len(data), data)

    @staticmethod
    def _decode(raw, signed, name):
        if name == "pantilt":
            return [int.from_bytes(raw[0:4], "little", signed=True), int.from_bytes(raw[4:8], "little", signed=True)]
        return int.from_bytes(raw, "little", signed=signed)

    @staticmethod
    def _encode(value, size, signed, name):
        if name == "pantilt":
            return int(value[0]).to_bytes(4, "little", signed=True) + int(value[1]).to_bytes(4, "little", signed=True)
        return int(value).to_bytes(size, "little", signed=signed)

    # -- API
    def get(self, name, request=GET_CUR):
        unit, sel, size, signed, _, _ = CONTROLS[name]
        return self._decode(self._get(unit, sel, request, size), signed, name)

    def describe(self, name):
        info = {"valeur": self.get(name)}
        for key, req in (("min", GET_MIN), ("max", GET_MAX), ("defaut", GET_DEF), ("pas", GET_RES)):
            try:
                info[key] = self.get(name, req)
            except USBError:
                pass
        return info

    def set(self, name, value):
        unit, sel, size, signed, _, named = CONTROLS[name]
        if isinstance(value, str) and named and value.lower() in named:
            value = named[value.lower()]
        if name == "pantilt" and isinstance(value, str):
            value = [int(v) for v in value.split(",")]
        elif not isinstance(value, list):
            value = int(value)
        if name not in ("pantilt", "exposure_auto"):        # borne la valeur dans [min, max]
            try:
                lo, hi = self.get(name, GET_MIN), self.get(name, GET_MAX)
                value = max(lo, min(hi, value))
            except USBError:
                pass
        try:
            self._set(unit, sel, self._encode(value, size, signed, name))
        except USBError as e:
            hint = ""
            if name in MANUAL_ONLY:
                dep, val = MANUAL_ONLY[name]
                hint = f" (il faut d'abord {dep}={val})"
            raise KiyoError(f"la caméra refuse {name}={value}{hint} : {e}") from e
        return value

    def snapshot(self):
        out = {}
        for name in APPLY_ORDER:
            try:
                out[name] = self.get(name)
            except USBError:
                pass
        return out

    def apply(self, settings, verbose=True):
        errors = []
        for name in APPLY_ORDER:
            if name not in settings:
                continue
            if name in MANUAL_ONLY:  # inutile (et refusé) d'écrire une valeur manuelle en mode auto
                dep, val = MANUAL_ONLY[name]
                if dep in settings and settings[dep] != val and not (dep == "exposure_auto" and settings[dep] == 4):
                    continue
            try:
                v = self.set(name, settings[name])
                if verbose:
                    print(f"  {name:20s} = {v}")
            except KiyoError as e:
                errors.append(str(e))
        for e in errors:
            print("  ! " + e, file=sys.stderr)
        return not errors

    def xu_dump(self):
        """Lecture seule des unités propriétaires : taille + valeur de chaque sélecteur."""
        rows = []
        for unit in XU_UNITS:
            for sel in range(1, 17):
                try:
                    ln = int.from_bytes(self._get(unit, sel, GET_LEN, 2), "little")
                    info = self._get(unit, sel, GET_INFO, 1)[0]
                    cur = self._get(unit, sel, GET_CUR, ln) if info & 1 else b""
                    rows.append((unit, sel, ln, info, cur))
                except USBError:
                    continue
        return rows


# ---------------------------------------------------------------- profils
def profile_path(name):
    return os.path.join(PROFILE_DIR, f"{name}.json")


def save_profile(kiyo, name):
    os.makedirs(PROFILE_DIR, exist_ok=True)
    data = kiyo.snapshot()
    with open(profile_path(name), "w") as f:
        json.dump(data, f, indent=2)
    return data


def load_profile(name):
    path = name if name.endswith(".json") else profile_path(name)
    if not os.path.exists(path):
        raise KiyoError(f"profil introuvable : {path}")
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------- commandes
def cmd_info(_args):
    Kiyo()  # vérifie qu'elle répond
    out = subprocess.run(["system_profiler", "SPUSBHostDataType"], capture_output=True, text=True).stdout
    block = out.split("Razer Kiyo:")[1].split("\n\n")[1] if "Razer Kiyo:" in out else ""
    print("Razer Kiyo (modèle d'origine)")
    for line in block.splitlines():
        line = line.strip()
        if line.split(":")[0] in ("Manufacturer", "Link Speed", "USB Vendor ID", "USB Product ID",
                                  "USB Product Version", "Power Allocated"):
            print("  " + line)
    print(f"UVC : Camera Terminal id={CT}, Processing Unit id={PU}, Extension Units {XU_UNITS}")
    print(f"{len(CONTROLS)} réglages standard disponibles (kiyoctl.py list)")


def cmd_list(_args):
    k = Kiyo()
    print(f"{'réglage':20s} {'valeur':>10s} {'min':>8s} {'max':>8s} {'défaut':>8s}  description")
    for name in APPLY_ORDER:
        try:
            i = k.describe(name)
        except USBError:
            print(f"{name:20s} {'(illisible)':>10s}")
            continue
        val = i["valeur"]
        named = CONTROLS[name][5]
        if named:
            rev = {v: n for n, v in named.items()}
            val = f"{val} ({rev.get(val, '?')})"
        f = lambda key: str(i.get(key, "-"))
        print(f"{name:20s} {str(val):>10s} {f('min'):>8s} {f('max'):>8s} {f('defaut'):>8s}  {CONTROLS[name][4]}")


def cmd_get(args):
    k = Kiyo()
    for name in args.names:
        if name not in CONTROLS:
            raise KiyoError(f"réglage inconnu : {name} (voir kiyoctl.py list)")
        print(f"{name} = {k.get(name)}")


def cmd_set(args):
    k = Kiyo()
    settings = {}
    for item in args.pairs:
        if "=" not in item:
            raise KiyoError(f"format attendu nom=valeur, reçu : {item}")
        name, value = item.split("=", 1)
        if name not in CONTROLS:
            raise KiyoError(f"réglage inconnu : {name} (voir kiyoctl.py list)")
        settings[name] = value
    for name in APPLY_ORDER:  # applique dans le bon ordre (modes auto d'abord)
        if name in settings:
            print(f"{name} = {k.set(name, settings[name])}")


def cmd_reset(_args):
    k = Kiyo()
    defaults = {}
    for name in APPLY_ORDER:
        try:
            defaults[name] = k.get(name, GET_DEF)
        except USBError:
            pass
    k.apply(defaults)


def cmd_save(args):
    data = save_profile(Kiyo(), args.name)
    print(f"Profil « {args.name} » enregistré ({len(data)} réglages) : {profile_path(args.name)}")


def cmd_load(args):
    print(f"Application du profil « {args.name} » :")
    Kiyo().apply(load_profile(args.name))


def cmd_profiles(_args):
    if not os.path.isdir(PROFILE_DIR):
        print("Aucun profil."); return
    for f in sorted(os.listdir(PROFILE_DIR)):
        if f.endswith(".json"):
            print(" -", f[:-5])


def cmd_watch(args):
    settings = load_profile(args.name)
    print(f"Veille : le profil « {args.name} » sera appliqué à chaque branchement de la Kiyo (Ctrl+C pour arrêter).")
    present, last_check = False, 0.0
    while True:
        dev = True if kiyo_present() else None
        now = time.time()
        if dev is not None and not present:
            time.sleep(1.5)  # laisse macOS initialiser la caméra
            try:
                print(time.strftime("%H:%M:%S"), "Kiyo détectée -> application du profil")
                Kiyo().apply(settings, verbose=False)
            except KiyoError as e:
                print("  !", e)
        elif dev is not None and now - last_check > 30:
            # vérifie périodiquement (le Mac peut tout remettre à zéro après une veille)
            try:
                k = Kiyo()
                drift = [n for n in ("focus_auto", "exposure_auto", "white_balance_auto")
                         if n in settings and k.get(n) != settings[n]]
                if drift:
                    print(time.strftime("%H:%M:%S"), "réglages modifiés", drift, "-> réapplication")
                    k.apply(settings, verbose=False)
            except KiyoError:
                pass
            last_check = now
        elif dev is None and present:
            print(time.strftime("%H:%M:%S"), "Kiyo débranchée")
        present = dev is not None
        time.sleep(args.interval)


def _sharpness(gray):
    """Netteté = variance du laplacien sur le centre de l'image (là où est le visage)."""
    import numpy as np
    h, w = gray.shape
    c = gray[h // 6: h * 5 // 6, w // 4: w * 3 // 4].astype(np.float32)
    lap = c[1:-1, 1:-1] * 4 - c[:-2, 1:-1] - c[2:, 1:-1] - c[1:-1, :-2] - c[1:-1, 2:]
    return float(lap.var())


def cmd_focus_lock(args):
    """Balaye la mise au point, mesure la netteté de l'image, garde la meilleure et la verrouille."""
    import numpy as np
    k = Kiyo()
    W, H = 640, 360
    stream = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "avfoundation",
                               "-framerate", "30", "-video_size", "1280x720", "-i", "Razer Kiyo",
                               "-vf", f"scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def frame():
        buf = stream.stdout.read(W * H)
        if len(buf) < W * H:
            raise KiyoError("pas d'image de la Kiyo (autorisation caméra pour ce terminal ?)")
        return np.frombuffer(buf, np.uint8).reshape(H, W)

    def measure(focus):
        k.set("focus", focus)
        for _ in range(8):            # laisse l'objectif bouger (~0,25 s)
            frame()
        return np.median([_sharpness(frame()) for _ in range(3)])

    try:
        k.set("focus_auto", 0)
        for _ in range(20):           # laisse l'exposition se stabiliser
            frame()
        lo, hi = k.get("focus", GET_MIN), k.get("focus", GET_MAX)
        print(f"Recherche de la meilleure mise au point ({lo}-{hi}) : restez à votre place…")
        coarse = {f: measure(f) for f in range(lo, hi + 1, 15)}
        best = max(coarse, key=coarse.get)
        fine = {f: measure(f) for f in range(max(lo, best - 12), min(hi, best + 12) + 1, 3)}
        best = max(fine, key=fine.get)
        k.set("focus", best)
    finally:
        stream.kill()
    curve = " ".join(f"{f}:{v:.0f}" for f, v in sorted(coarse.items()))
    print(f"Netteté par position : {curve}")
    print(f"Mise au point verrouillée à focus={best}")
    if args.profil:
        data = load_profile(args.profil) if os.path.exists(profile_path(args.profil)) else k.snapshot()
        data.update(focus_auto=0, focus=best)
        os.makedirs(PROFILE_DIR, exist_ok=True)
        with open(profile_path(args.profil), "w") as f:
            json.dump(data, f, indent=2)
        print(f"Enregistré dans le profil « {args.profil} »")


def cmd_xu_dump(_args):
    print("Lecture seule des unités propriétaires (rien n'est écrit) :")
    print(f"{'unité':>5s} {'sél.':>4s} {'taille':>6s} {'info':>5s}  valeur (hex)")
    for unit, sel, ln, info, cur in Kiyo().xu_dump():
        flags = ("G" if info & 1 else "-") + ("S" if info & 2 else "-")
        print(f"{unit:5d} {sel:4d} {ln:6d} {flags:>5s}  {cur.hex(' ')}")


def main():
    p = argparse.ArgumentParser(description="Contrôle de la Razer Kiyo (1532:0E03) sous macOS")
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("info").set_defaults(func=cmd_info)
    sp.add_parser("list").set_defaults(func=cmd_list)
    g = sp.add_parser("get"); g.add_argument("names", nargs="+"); g.set_defaults(func=cmd_get)
    s = sp.add_parser("set"); s.add_argument("pairs", nargs="+", metavar="nom=valeur"); s.set_defaults(func=cmd_set)
    sp.add_parser("reset").set_defaults(func=cmd_reset)
    for n, f in (("save", cmd_save), ("load", cmd_load)):
        x = sp.add_parser(n); x.add_argument("name"); x.set_defaults(func=f)
    sp.add_parser("profiles").set_defaults(func=cmd_profiles)
    w = sp.add_parser("watch"); w.add_argument("name"); w.add_argument("--interval", type=float, default=2.0)
    w.set_defaults(func=cmd_watch)
    fl = sp.add_parser("focus-lock", help="mise au point auto une fois, puis verrouillée")
    fl.add_argument("--profil", help="enregistrer la mise au point dans ce profil")
    fl.set_defaults(func=cmd_focus_lock)
    sp.add_parser("xu-dump").set_defaults(func=cmd_xu_dump)
    args = p.parse_args()
    try:
        args.func(args)
    except KiyoError as e:
        sys.exit(f"Erreur : {e}")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
