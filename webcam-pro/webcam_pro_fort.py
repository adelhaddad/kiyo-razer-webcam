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
  P       activer / désactiver le traitement (comparer avant / après)
  C       afficher la comparaison côte à côte
  Q / Échap  quitter

Note : sur macOS, OpenCV ne peut pas couper l'autofocus de la caméra.
Réglez la mise au point manuelle et le zoom une fois dans CameraController.

Exemples :
  python webcam_pro.py                 # aperçu en direct
  python webcam_pro.py --doux          # avec lissage de peau
  python webcam_pro.py --image in.jpg  # traiter une image existante
"""
import argparse
import os
import time
from datetime import datetime

import cv2
import numpy as np

cv2.setNumThreads(6)  # évite de saturer le processeur
SAVE_DIR = os.path.expanduser("~/Pictures/webcam-pro")


# ---------------------------------------------------------------- traitement
class Processor:
    """force : 0.5 = discret, 1 = normal, 1.5-2 = très visible."""

    def __init__(self, soft_skin=False, force=1.0):
        self.soft_skin = soft_skin
        self.force = force
        self.wb = None          # correction de couleur, lissée dans le temps
        self.gamma = None       # exposition, lissée dans le temps
        self.acc = None         # accumulateur du débruitage temporel
        self.face = None
        self.face_age = 999
        self.frame_i = 0
        lv = np.arange(256, dtype=np.float32)
        t = np.clip((lv - 20) / 90.0, 0, 1)
        self.wb_weight_lut = (t * t * (3 - 2 * t)).astype(np.float32)
        self.clahe = cv2.createCLAHE(clipLimit=1.5 + 1.0 * force, tileGridSize=(8, 8))
        self.face_front = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        self.face_prof = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")

    # -- débruitage temporel (vidéo) : moyenne des images là où rien ne bouge
    def temporal_denoise(self, img):
        f = img.astype(np.float32)
        if self.acc is None or self.acc.shape != f.shape:
            self.acc = f
            return img
        q = (f.shape[1] // 4, f.shape[0] // 4)
        diff = cv2.absdiff(cv2.resize(f, q, interpolation=cv2.INTER_AREA),
                           cv2.resize(self.acc, q, interpolation=cv2.INTER_AREA)).max(axis=2)
        alpha = np.clip(cv2.GaussianBlur(diff, (0, 0), 1.5) / 22.0, 0.22, 1.0)  # 0.22 ~ 5 images si immobile
        alpha = cv2.resize(alpha, (f.shape[1], f.shape[0]))
        d = cv2.subtract(f, self.acc)
        cv2.multiply(d, cv2.merge([alpha, alpha, alpha]), dst=d)
        cv2.add(self.acc, d, dst=self.acc)
        return self.acc.astype(np.uint8)

    # -- détection du visage (pour régler l'exposition dessus, comme un téléphone)
    def detect_face(self, img):
        self.frame_i += 1
        self.face_age += 1
        if self.frame_i % 6 == 1:                      # détection toutes les 6 images
            sc = 480.0 / img.shape[1]
            g = cv2.equalizeHist(cv2.cvtColor(cv2.resize(img, None, fx=sc, fy=sc), cv2.COLOR_BGR2GRAY))
            gf = cv2.flip(g, 1)
            found = list(self.face_front.detectMultiScale(g, 1.08, 3, minSize=(30, 30)))
            found += list(self.face_prof.detectMultiScale(g, 1.08, 2, minSize=(30, 30)))
            found += [(g.shape[1] - x - w, y, w, h)          # profil tourné de l'autre côté
                      for (x, y, w, h) in self.face_prof.detectMultiScale(gf, 1.08, 2, minSize=(30, 30))]
            if found:
                x, y, w, h = max(found, key=lambda r: r[2] * r[3])
                self.face = tuple(int(v / sc) for v in (x, y, w, h))
                self.face_age = 0
        return self.face if self.face_age < 45 else None

    def exposure_lut(self, L, face, smooth):
        h, w = L.shape
        if face is not None:
            x, y, fw, fh = face
            roi = L[y + fh // 5: y + fh * 4 // 5, x + fw // 5: x + fw * 4 // 5]
            target = 118 + 12 * (self.force - 1)
        else:
            roi = L[h // 8: h * 3 // 5, w // 4: w * 3 // 4]
            target = 108 + 10 * (self.force - 1)
        m = float(np.clip(roi.mean() if roi.size else L.mean(), 5, 250))
        g = np.log(target / 255.0) / np.log(m / 255.0)
        g = float(np.clip(g, 0.38, 1.25))
        self.gamma = g if (self.gamma is None or smooth == 0) else smooth * self.gamma + (1 - smooth) * g
        x = np.arange(256, dtype=np.float32) / 255.0
        y = np.power(x, self.gamma)
        y = y * 0.97 + 0.03 * (x * x * (3 - 2 * x))          # garde de vrais noirs
        return np.clip(y * 255, 0, 255).astype(np.uint8)

    def white_balance_shift(self, lab, smooth):
        """Mesure la dominante de couleur (en ignorant les couleurs très vives)
        et en retire une partie : on garde l'ambiance mais on n'a plus l'air bleu."""
        small = cv2.resize(lab, (160, 90), interpolation=cv2.INTER_AREA).astype(np.float32)
        L, a, b = small[..., 0], small[..., 1] - 128, small[..., 2] - 128
        chroma = np.sqrt(a ** 2 + b ** 2)
        mask = (L > 25) & (L < 245) & (chroma < 90)
        if mask.sum() < 150:
            shift = np.zeros(2, np.float32)
        else:
            amount = float(np.clip(0.5 * self.force, 0, 0.9))
            shift = np.clip(-amount * np.array([a[mask].mean(), b[mask].mean()], np.float32), -25, 25)
        self.wb = shift if (self.wb is None or smooth == 0) else smooth * self.wb + (1 - smooth) * shift
        return self.wb

    def process(self, img, smooth_wb=0.9, live=False):
        if live:
            img = self.temporal_denoise(img)
        face = self.detect_face(img)

        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        L, a, b = cv2.split(lab)

        # 1. exposition (sur le visage si trouvé)
        L = cv2.LUT(L, self.exposure_lut(L, face, smooth_wb))

        # 2. couleur
        da, db = self.white_balance_shift(cv2.merge([L, a, b]), smooth_wb)
        # correction appliquée surtout aux tons moyens/clairs (évite les noirs verdâtres)
        wl = cv2.resize(self.wb_weight_lut[cv2.resize(L, (L.shape[1] // 4, L.shape[0] // 4))], (L.shape[1], L.shape[0]))
        a = a.astype(np.float32) + float(da) * wl
        b = b.astype(np.float32) + float(db) * wl

        # 3. contraste local (fait ressortir les détails sans tout brûler)
        mix = float(np.clip(0.45 * self.force, 0, 0.9))
        L = cv2.addWeighted(L, 1 - mix, self.clahe.apply(L), mix, 0)

        # 4. netteté sur la luminance seule
        amt = 0.5 * self.force
        blur = cv2.GaussianBlur(L, (0, 0), 1.3)
        L = cv2.addWeighted(L, 1 + amt, blur, -amt, 0)

        # 5. vibrance + réduction du bruit de couleur
        a_f, b_f = a - 128, b - 128
        chroma = np.sqrt(a_f ** 2 + b_f ** 2)
        boost = 1.0 + 0.25 * self.force * np.clip(1 - chroma / 60.0, 0, 1)
        a = cv2.GaussianBlur(np.clip(a_f * boost + 128, 0, 255).astype(np.uint8), (0, 0), 1.2)
        b = cv2.GaussianBlur(np.clip(b_f * boost + 128, 0, 255).astype(np.uint8), (0, 0), 1.2)

        out = cv2.cvtColor(cv2.merge([L, a, b]), cv2.COLOR_LAB2BGR)
        if self.soft_skin:
            smooth = cv2.bilateralFilter(out, 9, 40, 9)
            out = cv2.addWeighted(out, 0.6, smooth, 0.4, 0)
        return out


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


def take_photo(cap, proc, n=10):
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
    out = proc.process(fused, smooth_wb=0.0)
    os.makedirs(SAVE_DIR, exist_ok=True)
    path = os.path.join(SAVE_DIR, datetime.now().strftime("photo_%Y%m%d_%H%M%S.jpg"))
    cv2.imwrite(path, out, [cv2.IMWRITE_JPEG_QUALITY, 95])
    cv2.imwrite(path.replace(".jpg", "_brut.jpg"), frames[0], [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"Photo enregistrée : {path}  ({used} images fusionnées)")
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
    proc = Processor(soft_skin=args.doux, force=args.force)
    cap = open_camera(args.camera, args.width, args.height, args.fps)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Caméra ouverte en {w}x{h}. ESPACE=photo  P=traitement on/off  C=comparaison  Q=quitter")
    enabled, compare = True, False
    t0, n = time.time(), 0
    fps_txt = ""
    while True:
        ok, frame = cap.read()
        if not ok:
            print("Plus d'image de la caméra."); break
        if frame.shape[1] > 1280:                     # aperçu en 720p (fluide) ; photos en 1080p
            frame = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
        processed = proc.process(frame, live=True)
        view = processed if enabled else frame
        if compare:
            view = np.hstack([frame, processed])
        n += 1
        if time.time() - t0 > 1:
            fps_txt = f"{n / (time.time() - t0):.0f} fps"; t0, n = time.time(), 0
        disp = cv2.resize(view, None, fx=0.75, fy=0.75) if view.shape[1] > 1600 else view.copy()
        label = "COMPARAISON (gauche: brut)" if compare else ("TRAITE" if enabled else "BRUT")
        cv2.putText(disp, f"{label}  {fps_txt}", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.imshow("webcam pro", disp)
        k = cv2.waitKey(1) & 0xFF
        if k in (ord("q"), 27):
            break
        elif k == ord("p"):
            enabled = not enabled
        elif k == ord("c"):
            compare = not compare
        elif k == 32:
            photo = take_photo(cap, Processor(soft_skin=args.doux, force=args.force), args.burst)
            cv2.imshow("photo", cv2.resize(photo, None, fx=0.5, fy=0.5))
    cap.release()
    cv2.destroyAllWindows()


def main():
    p = argparse.ArgumentParser(description="Webcam façon smartphone")
    p.add_argument("--camera", type=int, default=0, help="index de la caméra (0 = Razer Kiyo)")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--burst", type=int, default=10, help="images fusionnées par photo")
    p.add_argument("--force", type=float, default=1.3, help="intensité du traitement (0.5 discret, 1 normal, 2 très fort)")
    p.add_argument("--doux", action="store_true", help="lissage de peau léger")
    p.add_argument("--image", help="traiter un fichier image au lieu de la caméra")
    p.add_argument("--out", help="fichier de sortie pour --image")
    args = p.parse_args()

    if args.image:
        img = cv2.imread(args.image)
        if img is None:
            raise SystemExit(f"Image illisible : {args.image}")
        proc = Processor(soft_skin=args.doux, force=args.force)
        img = auto_denoise(img)
        out = proc.process(img, smooth_wb=0.0)
        dst = args.out or os.path.splitext(args.image)[0] + "_pro.jpg"
        cv2.imwrite(dst, out, [cv2.IMWRITE_JPEG_QUALITY, 95])
        print(f"Enregistré : {dst}")
    else:
        live(args)


if __name__ == "__main__":
    main()
