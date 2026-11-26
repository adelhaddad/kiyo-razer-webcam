"""
Améliorations par IA pour webcam_pro.py

- LowLight    : Zero-DCE++ (Li Chongyi et al., https://github.com/Li-Chongyi/Zero-DCE_extension)
                éclaircit les scènes sombres, assez léger pour la vidéo en direct.
                Licence des poids : usage non commercial.
- FaceRestore : GFPGAN v1.4 (TencentARC, https://github.com/TencentARC/GFPGAN)
                rend le visage plus net et détaillé ; trop lent pour la vidéo -> photos seulement.
"""
import os

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- Zero-DCE++
class _CSDN_Tem(nn.Module):  # même structure que le code officiel (pour charger les poids)
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.depth_conv = nn.Conv2d(in_ch, in_ch, 3, 1, 1, groups=in_ch)
        self.point_conv = nn.Conv2d(in_ch, out_ch, 1, 1, 0)

    def forward(self, x):
        return self.point_conv(self.depth_conv(x))


class _ZeroDCEpp(nn.Module):
    def __init__(self):
        super().__init__()
        n = 32
        self.e_conv1 = _CSDN_Tem(3, n)
        self.e_conv2 = _CSDN_Tem(n, n)
        self.e_conv3 = _CSDN_Tem(n, n)
        self.e_conv4 = _CSDN_Tem(n, n)
        self.e_conv5 = _CSDN_Tem(n * 2, n)
        self.e_conv6 = _CSDN_Tem(n * 2, n)
        self.e_conv7 = _CSDN_Tem(n * 2, 3)

    def curves(self, x):
        """Renvoie les 'courbes' d'éclaircissement (une par pixel et par couleur)."""
        x1 = F.relu(self.e_conv1(x))
        x2 = F.relu(self.e_conv2(x1))
        x3 = F.relu(self.e_conv3(x2))
        x4 = F.relu(self.e_conv4(x3))
        x5 = F.relu(self.e_conv5(torch.cat([x3, x4], 1)))
        x6 = F.relu(self.e_conv6(torch.cat([x2, x5], 1)))
        return torch.tanh(self.e_conv7(torch.cat([x1, x6], 1)))


class LowLight:
    """Zero-DCE++ : les courbes sont calculées sur une petite image (rapide),
    puis appliquées à l'image en pleine résolution, comme dans l'article."""

    def __init__(self, strength=0.7, weights=os.path.join(HERE, "models", "zero_dce_pp.pth")):
        self.net = _ZeroDCEpp()
        state = torch.load(weights, map_location="cpu")
        state = {k.replace("module.", ""): v for k, v in state.items()}
        self.net.load_state_dict(state)
        self.net.eval()
        self.strength = strength
        torch.set_num_threads(4)

    @torch.no_grad()
    def apply(self, img_bgr):
        h, w = img_bgr.shape[:2]
        sw, sh = max(64, w // 4), max(36, h // 4)
        small = cv2.resize(img_bgr, (sw, sh), interpolation=cv2.INTER_AREA)[..., ::-1].astype(np.float32) / 255.0
        t = torch.from_numpy(np.ascontiguousarray(small.transpose(2, 0, 1)))[None]
        r = self.net.curves(t)[0].numpy().transpose(1, 2, 0)
        y = small
        for _ in range(8):                                             # 8 itérations de la courbe
            y = y + r * (y * y - y)
        # rapide : on calcule un "gain" sur la petite image puis on l'applique en pleine résolution
        gain = (np.clip(y, 0, 1) + 0.03) / (small + 0.03)
        gain = 1.0 + self.strength * (gain - 1.0)                     # intensité réglable
        gain = cv2.GaussianBlur(gain[..., ::-1], (0, 0), 1.0)          # retour en BGR, lissé
        gain = cv2.resize(gain, (w, h), interpolation=cv2.INTER_LINEAR)
        out = np.clip(img_bgr.astype(np.float32) * gain, 0, 255).astype(np.uint8)
        # on garde les couleurs d'origine : éclaircir ne doit pas jaunir/orangir la peau
        lab_o = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
        lab_n = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
        lab_n[..., 1:] = lab_o[..., 1:]
        return cv2.cvtColor(lab_n, cv2.COLOR_LAB2BGR)


# ---------------------------------------------------------------- GFPGAN
class FaceRestore:
    def __init__(self, strength=0.35, device=None):
        from gfpgan import GFPGANer
        if device is None:
            device = "mps" if torch.backends.mps.is_available() else "cpu"
        cwd = os.getcwd()
        os.chdir(HERE)  # facexlib cherche ses poids dans ./gfpgan/weights
        try:
            self.restorer = GFPGANer(
                model_path=os.path.join(HERE, "gfpgan", "weights", "GFPGANv1.4.pth"),
                upscale=1, arch="clean", channel_multiplier=2, bg_upsampler=None,
                device=torch.device(device))
        finally:
            os.chdir(cwd)
        self.strength = strength

    def apply(self, img_bgr):
        """Renvoie (image, nombre de visages restaurés)."""
        _, faces, restored = self.restorer.enhance(
            img_bgr, has_aligned=False, only_center_face=False, paste_back=True)
        if restored is None or not faces:
            return img_bgr, 0
        if restored.shape != img_bgr.shape:
            restored = cv2.resize(restored, (img_bgr.shape[1], img_bgr.shape[0]))
        # mélange léger avec l'original, et SEULEMENT sur les détails (luminance) :
        # la couleur de la peau reste exactement celle de la photo
        mixed = cv2.addWeighted(img_bgr, 1 - self.strength, restored, self.strength, 0)
        lab_o = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
        lab_m = cv2.cvtColor(mixed, cv2.COLOR_BGR2LAB)
        lab_o[..., 0] = lab_m[..., 0]
        return cv2.cvtColor(lab_o, cv2.COLOR_LAB2BGR), len(faces)
