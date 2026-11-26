"""Capture quelques images brutes de chaque caméra (pour comparer et régler)."""
import os, sys, time
import cv2
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
for i in (0, 1):
    cap = cv2.VideoCapture(i, cv2.CAP_AVFOUNDATION)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    frames, t = [], time.time()
    while time.time() - t < 4:          # laisse l'exposition auto se stabiliser
        ok, f = cap.read()
        if ok:
            frames.append(f)
    print(f"camera {i}: {len(frames)} images", frames[-1].shape if frames else "AUCUNE")
    for j, f in enumerate(frames[-10:]):
        cv2.imwrite(os.path.join(out, f"cam{i}_{j}.png"), f)
    cap.release()
open(os.path.join(out, "FINI"), "w").write("ok")
