#!/usr/bin/env python3
"""
webcam_pro.py — webcam "façon smartphone" pour Razer Kiyo (ou toute webcam).

Ce que fait le script (comme un iPhone / Samsung, en plus simple) :
  1. Capture en 1080p (MJPEG).
  2. Mode PHOTO : rafale de plusieurs images, alignement puis fusion
     -> beaucoup moins de bruit (principe du "HDR+ / Deep Fusion").
  3. Balance des blancs automatique douce (stable, sans clignotement).
  4. Tone mapping local : ombres débouchées, hautes lumières préservées.
  5. Couleurs plus vivantes (vibrance) sans brûler la peau.
  6. Netteté fine uniquement sur la luminance (pas de halos colorés).
  7. Option peau lissée (--doux).

Touches pendant l'aperçu :
  ESPACE  photo haute qualité (rafale + fusion), enregistrée dans ~/Pictures/webcam-pro
  F       fond flou (mode Portrait) on/off ;  + / -  plus ou moins de flou
  L       mode nuit (Zero-DCE++) on/off : éclaircit une pièce sombre
  G       visage IA (GFPGAN) on/off pour les photos : visage plus net
  P       activer / désactiver le traitement (comparer avant / après)
  C       afficher la comparaison côte à côte
  Q / Échap  quitter

Note : sur macOS, OpenCV ne peut pas couper l'autofocus de la caméra.
Réglez la mise au point manuelle et le zoom une fois dans CameraController.

Exemples :
  python webcam_pro.py                 # aperçu en direct
  python webcam_pro.py --doux          # avec lissage de peau
  python webcam_pro.py --camera 1      # 2e caméra (PC-LM1E)
  python webcam_pro.py --double        # les deux caméras côte à côte
  python webcam_pro.py --image in.jpg  # traiter une image existante
"""
import argparse
import os
import threading
import time
from datetime import datetime

import cv2
import numpy as np

SAVE_DIR = os.path.expanduser("~/Pictures/webcam-pro")

# Réglages propres à chaque caméra (index OpenCV -> profil). Adaptez-les à vos caméras.
#   wb      : force de la correction de couleur (0 = aucune, 1 = neutre complet)
#   wb_max  : correction maximale
#   wb_gris : jusqu'à quelle saturation un pixel compte comme "presque gris"
#   nuit    : mode nuit (Zero-DCE++) activé au démarrage, et son intensité
PROFILS = {
    0: dict(nom="Razer Kiyo", wb=0.6, wb_max=16, wb_gris=40, nuit=True, nuit_force=0.8),
    1: dict(nom="PC-LM1E", wb=0.65, wb_max=14, wb_gris=32, nuit=False, nuit_force=0.5),
}
PROFIL_DEFAUT = dict(nom="caméra", wb=0.4, wb_max=10, wb_gris=25, nuit=False, nuit_force=0.7)


# ---------------------------------------------------------------- traitement
class Processor:
    def __init__(self, soft_skin=False, profil=None):
        self.soft_skin = soft_skin
        self.profil = profil or PROFIL_DEFAUT
        self.wb_gains = None  # lissées dans le temps pour éviter le scintillement
        self.clahe = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8))
        # Courbe de tons : légère courbe en S + ombres un peu relevées
        x = np.arange(256, dtype=np.float32) / 255.0
        lifted = x + 0.10 * x * (1 - x) ** 2 * 4          # relève les ombres
        s_curve = lifted + 0.06 * np.sin(2 * np.pi * lifted) * -0.5  # contraste doux
        self.tone_lut = np.clip(s_curve * 255, 0, 255).astype(np.uint8)

    def white_balance_shift(self, lab, smooth=0.9):
        """Mesure la dominante de couleur uniquement sur les pixels presque gris
        (murs, vêtements neutres...) et la corrige à moitié : plus fiable que
        'gray world', ne transforme pas un mur coloré ou la peau en gris."""
        small = cv2.resize(lab, (160, 90), interpolation=cv2.INTER_AREA).astype(np.float32)
        L, a, b = small[..., 0], small[..., 1] - 128, small[..., 2] - 128
        chroma = np.sqrt(a ** 2 + b ** 2)
        mask = (L > 30) & (L < 240) & (chroma < self.profil["wb_gris"])
        if mask.sum() < 150:
            shift = np.zeros(2, np.float32)  # pas assez de gris : on ne touche à rien
        else:
            shift = -self.profil["wb"] * np.array([a[mask].mean(), b[mask].mean()], np.float32)
            shift = np.clip(shift, -self.profil["wb_max"], self.profil["wb_max"])
        if self.wb_gains is None or smooth == 0:
            self.wb_gains = shift
        else:
            self.wb_gains = smooth * self.wb_gains + (1 - smooth) * shift
        return self.wb_gains

    def process(self, img, smooth_wb=0.9):
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        da, db = self.white_balance_shift(lab, smooth_wb)
        L, a, b = cv2.split(lab)
        # masque "peau" (tons chair) : on n'y touche presque pas, pour un visage naturel
        a0 = a.astype(np.float32) - 128
        b0 = b.astype(np.float32) - 128
        skin = ((a0 > 4) & (a0 < 35) & (b0 > 4) & (b0 < 40) & (b0 < a0 * 2.2 + 8)).astype(np.float32)
        skin = cv2.GaussianBlur(skin, (0, 0), 3)
        self.skin = skin
        da_px = float(da) * (1 - 0.8 * skin)
        db_px = float(db) * (1 - 0.8 * skin)
        a = np.clip(a0 + 128 + da_px, 0, 255).astype(np.uint8)
        b = np.clip(b0 + 128 + db_px, 0, 255).astype(np.uint8)

        # tone mapping local (CLAHE) mélangé pour rester naturel
        L_local = self.clahe.apply(L)
        L = cv2.addWeighted(L, 0.45, L_local, 0.55, 0)
        L = cv2.LUT(L, self.tone_lut)

        # netteté (unsharp mask) sur la luminance seule
        blur = cv2.GaussianBlur(L, (0, 0), 1.3)
        L = cv2.addWeighted(L, 1.55, blur, -0.55, 0)

        # vibrance : renforce plus les couleurs ternes que les couleurs déjà saturées
        a_f = a.astype(np.float32) - 128
        b_f = b.astype(np.float32) - 128
        chroma = np.sqrt(a_f ** 2 + b_f ** 2)
        boost = 1.0 + 0.22 * np.clip(1 - chroma / 60.0, 0, 1) * (1 - self.skin)  # pas de vibrance sur la peau
        a = np.clip(a_f * boost + 128, 0, 255).astype(np.uint8)
        b = np.clip(b_f * boost + 128, 0, 255).astype(np.uint8)
        # réduit le bruit de couleur (chroma) sans toucher aux détails
        a = cv2.GaussianBlur(a, (0, 0), 1.0)
        b = cv2.GaussianBlur(b, (0, 0), 1.0)

        out = cv2.cvtColor(cv2.merge([L, a, b]), cv2.COLOR_LAB2BGR)

        if self.soft_skin:
            smooth = cv2.bilateralFilter(out, 9, 40, 9)
            out = cv2.addWeighted(out, 0.6, smooth, 0.4, 0)
        return out


# ---------------------------------------------------------------- fond flou
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "selfie_segmenter.tflite")


class BackgroundBlur:
    """Mode Portrait : détecte la personne (MediaPipe) et floute l'arrière-plan."""

    def __init__(self, strength=1.0):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        self.mp = mp
        opts = vision.ImageSegmenterOptions(
            base_options=BaseOptions(model_asset_path=MODEL_PATH),
            running_mode=vision.RunningMode.VIDEO,
            output_confidence_masks=True)
        self.seg = vision.ImageSegmenter.create_from_options(opts)
        self.strength = strength
        self.mask = None
        self.ts = 0

    def person_mask(self, img, smooth=0.5):
        small = cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA)
        mp_img = self.mp.Image(image_format=self.mp.ImageFormat.SRGB,
                               data=cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
        self.ts += 33
        res = self.seg.segment_for_video(mp_img, self.ts)
        m = np.array(res.confidence_masks[-1].numpy_view(), dtype=np.float32).squeeze()
        if self.mask is None or self.mask.shape != m.shape or smooth == 0:
            self.mask = m
        else:  # lissage dans le temps : pas de bords qui tremblent
            self.mask = smooth * self.mask + (1 - smooth) * m
        return self.mask

    def apply(self, img, src=None, smooth=0.5):
        """img = image à flouter (déjà améliorée), src = image brute pour la détection."""
        h, w = img.shape[:2]
        m = self.person_mask(src if src is not None else img, smooth)
        m = cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)
        # affine les bords (cheveux, lunettes) en suivant les contours de l'image
        guide = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        if hasattr(cv2, "ximgproc"):
            m = cv2.ximgproc.guidedFilter(guide, m, radius=max(4, w // 160), eps=1e-3)
        m = np.nan_to_num(m, nan=0.0)
        m = np.clip((m - 0.35) / 0.4, 0, 1)                 # bord net mais doux
        m3 = cv2.merge([m, m, m])

        # flou "objectif" : on floute le fond SANS la personne (pas de halo autour)
        k = 1.0 - m3
        sc = 4
        sw, sh = w // sc, h // sc
        sigma = max(1.0, 6.0 * self.strength)
        fsmall = cv2.resize(img.astype(np.float32) * k, (sw, sh), interpolation=cv2.INTER_AREA)
        ksmall = cv2.resize(k, (sw, sh), interpolation=cv2.INTER_AREA)
        fsmall = cv2.GaussianBlur(fsmall, (0, 0), sigma)
        ksmall = cv2.GaussianBlur(ksmall, (0, 0), sigma)
        bg = cv2.resize(fsmall / np.maximum(ksmall, 1e-3), (w, h), interpolation=cv2.INTER_LINEAR)
        out = img.astype(np.float32) * m3 + bg * (1.0 - m3)
        return np.clip(out, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- rafale
def fuse_burst(frames):
    """Aligne les images sur la première (translation) puis fait une moyenne robuste."""
    ref = frames[0]
    ref_g = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype(np.float32)
    win = cv2.createHanningWindow(ref_g.shape[::-1], cv2.CV_32F)
    aligned = [ref.astype(np.float32)]
    for f in frames[1:]:
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
        (dx, dy), resp = cv2.phaseCorrelate(ref_g, g, win)
        if resp < 0.05 or abs(dx) > 40 or abs(dy) > 40:
            continue  # image floue ou trop bougée : ignorée
        M = np.float32([[1, 0, -dx], [0, 1, -dy]])
        aligned.append(cv2.warpAffine(f, M, (f.shape[1], f.shape[0]),
                                      borderMode=cv2.BORDER_REFLECT).astype(np.float32))
    stack = np.stack(aligned)
    # moyenne "tronquée" : écarte les pixels qui bougent (fantômes)
    med = np.median(stack, axis=0)
    weights = np.exp(-((stack - med) ** 2).sum(axis=3, keepdims=True) / (2 * 25.0 ** 2))
    fused = (stack * weights).sum(axis=0) / np.maximum(weights.sum(axis=0), 1e-6)
    return np.clip(fused, 0, 255).astype(np.uint8), len(aligned)


def auto_denoise(img):
    """Estime le niveau de bruit puis débruite juste ce qu'il faut."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    resid = g - cv2.GaussianBlur(g, (0, 0), 1.0)
    sigma = 1.4826 * float(np.median(np.abs(resid - np.median(resid)))) * 1.6
    h = float(np.clip(sigma * 0.9, 2, 12))
    return cv2.fastNlMeansDenoisingColored(img, None, h, h, 5, 15)


def sharpness(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(g, cv2.CV_64F).var()


class LazyFace:
    """Charge GFPGAN en arrière-plan (quelques secondes) pour ne pas bloquer l'aperçu."""

    def __init__(self):
        self.model, self.error = None, None
        self.thread = threading.Thread(target=self._load, daemon=True)
        self.thread.start()

    def _load(self):
        try:
            from ameliorations import FaceRestore
            self.model = FaceRestore()
        except Exception as e:  # noqa: BLE001
            self.error = e

    def get(self):
        self.thread.join()
        if self.error:
            print(f"GFPGAN indisponible : {self.error}")
        return self.model


def take_photo(cap, proc, n=10, blur=None, lowlight=None, face=None, tag=""):
    frames = []
    for _ in range(n + 4):
        ok, f = cap.read()
        if ok:
            frames.append(f)
    # garde les images les plus nettes (élimine celles où l'autofocus "pompe")
    frames.sort(key=sharpness, reverse=True)
    frames = frames[:n]
    fused, used = fuse_burst(frames)
    fused = auto_denoise(fused)
    base = lowlight.apply(fused) if lowlight is not None else fused
    out = proc.process(base, smooth_wb=0.0)
    os.makedirs(SAVE_DIR, exist_ok=True)
    path = os.path.join(SAVE_DIR, datetime.now().strftime("photo_%Y%m%d_%H%M%S") + tag + ".jpg")
    extra = ""
    model = face.get() if face is not None else None
    if model is not None:
        before = blur.apply(out, fused, smooth=0) if blur is not None else out
        cv2.imwrite(path.replace(".jpg", "_sans_ia.jpg"), before, [cv2.IMWRITE_JPEG_QUALITY, 95])
        out, nf = model.apply(out)
        extra = f", {nf} visage(s) amélioré(s) par GFPGAN"
    if blur is not None:
        out = blur.apply(out, fused, smooth=0)
    cv2.imwrite(path, out, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"Photo enregistrée : {path}  ({used} images fusionnées{extra})")
    return out


# ---------------------------------------------------------------- caméra
def open_camera(index, width, height, fps):
    cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION if os.uname().sysname == "Darwin" else cv2.CAP_ANY)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)  # ignoré sur macOS, utile sous Linux/Windows
    if not cap.isOpened():
        raise SystemExit(
            "Impossible d'ouvrir la caméra.\n"
            "-> Réglages Système > Confidentialité et sécurité > Caméra : autorisez le Terminal.\n"
            "-> Fermez Photo Booth / Teams / Zoom s'ils utilisent la caméra.")
    return cap


def live(args):
    indexes = [0, 1] if args.double else [args.camera]
    cams = []
    for i in indexes:
        cap = open_camera(i, args.width, args.height, args.fps)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"Caméra {i} ouverte en {w}x{h}")
        profil = PROFILS.get(i, PROFIL_DEFAUT)
        print(f"  -> réglages « {profil['nom']} »" + (" + mode nuit" if (profil["nuit"] and not args.sans_nuit) else ""))
        cams.append({"index": i, "cap": cap, "profil": profil, "proc": Processor(soft_skin=args.doux, profil=profil),
                     "nuit": args.nuit or (profil["nuit"] and not args.sans_nuit), "lowlight": None,
                     "blur": None if args.sans_flou else BackgroundBlur(args.flou)})
    blur_on = not args.sans_flou
    blur_strength = args.flou
    from ameliorations import LowLight
    for c in cams:
        force = args.nuit_force if args.nuit_force is not None else c["profil"]["nuit_force"]
        c["lowlight"] = LowLight(force)
    face = None if args.sans_visage_ia else LazyFace()
    face_on = face is not None
    double = len(cams) > 1
    print("ESPACE=photo  F=fond flou  L=mode nuit  G=visage IA  P=traitement  C=comparaison  Q=quitter")
    enabled, compare = True, False
    t0, n = time.time(), 0
    fps_txt = ""
    while True:
        tiles = []
        for c in cams:
            ok, full = c["cap"].read()
            if not ok:
                full = np.zeros((720, 1280, 3), np.uint8)
                cv2.putText(full, f"camera {c['index']} : pas d'image", (40, 360), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
            # aperçu en 720p pour rester fluide ; les photos restent en pleine résolution
            frame = cv2.resize(full, (1280, 720), interpolation=cv2.INTER_AREA) if full.shape[:2] != (720, 1280) else full
            base = c["lowlight"].apply(frame) if c["nuit"] else frame
            processed = c["proc"].process(base)
            if blur_on:
                if c["blur"] is None:
                    c["blur"] = BackgroundBlur(blur_strength)
                c["blur"].strength = blur_strength
                processed = c["blur"].apply(processed, frame)
            view = processed if enabled else frame
            if compare:
                view = np.hstack([frame, processed])
            if double:
                view = cv2.resize(view, None, fx=0.5, fy=0.5)
                cv2.putText(view, f"camera {c['index']}", (12, view.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            tiles.append(view)
        view = np.vstack(tiles) if (double and compare) else np.hstack(tiles)
        n += 1
        if time.time() - t0 > 1:
            fps_txt = f"{n / (time.time() - t0):.0f} fps"; t0, n = time.time(), 0
        disp = cv2.resize(view, None, fx=0.75, fy=0.75) if view.shape[1] > 1600 else view.copy()
        label = "COMPARAISON (gauche: brut)" if compare else ("TRAITE" if enabled else "BRUT")
        if enabled or compare:
            label += (" + NUIT" if any(c["nuit"] for c in cams) else "") + (" + FOND FLOU" if blur_on else "")
            label += " | photo: visage IA" if face_on else ""
        cv2.putText(disp, f"{label}  {fps_txt}", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.imshow("webcam pro", disp)
        k = cv2.waitKey(1) & 0xFF
        if k in (ord("q"), 27):
            break
        elif k == ord("p"):
            enabled = not enabled
        elif k == ord("c"):
            compare = not compare
        elif k == ord("f"):
            blur_on = not blur_on
        elif k == ord("l"):
            new = not any(c["nuit"] for c in cams)
            for c in cams:
                c["nuit"] = new
        elif k == ord("g"):
            if face is None:
                face = LazyFace()
            face_on = not face_on
            print("Visage IA (photos) :", "activé" if face_on else "désactivé")
        elif k == ord("+") or k == ord("="):
            blur_strength = min(3.0, blur_strength + 0.25); print(f"flou {blur_strength:.2f}")
        elif k == ord("-"):
            blur_strength = max(0.25, blur_strength - 0.25); print(f"flou {blur_strength:.2f}")
        elif k == 32:
            print("Photo en cours…")
            for c in cams:
                photo = take_photo(c["cap"], Processor(soft_skin=args.doux, profil=c["profil"]), args.burst,
                                   c["blur"] if blur_on else None, c["lowlight"] if c["nuit"] else None,
                                   face if face_on else None, tag=f"_cam{c['index']}" if double else "")
                cv2.imshow(f"photo camera {c['index']}", cv2.resize(photo, None, fx=0.5, fy=0.5))
    for c in cams:
        c["cap"].release()
    cv2.destroyAllWindows()


def main():
    p = argparse.ArgumentParser(description="Webcam façon smartphone")
    p.add_argument("--camera", type=int, default=1, help="index de la caméra (1 = PC-LM1E, par défaut ; 0 = Razer Kiyo)")
    p.add_argument("--double", action="store_true", help="les deux caméras en même temps, côte à côte")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--burst", type=int, default=10, help="images fusionnées par photo")
    p.add_argument("--doux", action="store_true", help="lissage de peau léger")
    p.add_argument("--flou", type=float, default=1.0, help="intensité du fond flou (0.5 léger, 1 normal, 2 fort)")
    p.add_argument("--nuit", action="store_true", help="démarrer en mode nuit (Zero-DCE++), touche L")
    p.add_argument("--nuit-force", type=float, default=None, help="intensité du mode nuit (0.3 léger, 1 fort ; par défaut selon la caméra)")
    p.add_argument("--sans-nuit", action="store_true", help="ne pas activer le mode nuit automatiquement (Kiyo)")
    p.add_argument("--sans-visage-ia", action="store_true", help="photos sans GFPGAN (touche G)")
    p.add_argument("--sans-flou", action="store_true", help="démarrer sans fond flou (touche F pour l'activer)")
    p.add_argument("--image", help="traiter un fichier image au lieu de la caméra")
    p.add_argument("--out", help="fichier de sortie pour --image")
    args = p.parse_args()

    if args.image:
        img = cv2.imread(args.image)
        if img is None:
            raise SystemExit(f"Image illisible : {args.image}")
        proc = Processor(soft_skin=args.doux)
        img = auto_denoise(img)
        base = img
        if args.nuit:
            from ameliorations import LowLight
            base = LowLight(args.nuit_force or 0.7).apply(img)
        out = proc.process(base, smooth_wb=0.0)
        if not args.sans_visage_ia:
            from ameliorations import FaceRestore
            out, nf = FaceRestore().apply(out)
            print(f"{nf} visage(s) amélioré(s) par GFPGAN")
        if not args.sans_flou:
            out = BackgroundBlur(args.flou).apply(out, img, smooth=0)
        dst = args.out or os.path.splitext(args.image)[0] + "_pro.jpg"
        cv2.imwrite(dst, out, [cv2.IMWRITE_JPEG_QUALITY, 95])
        print(f"Enregistré : {dst}")
    else:
        live(args)


if __name__ == "__main__":
    main()
