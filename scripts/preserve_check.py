"""Checks for cases without a ground truth: what had to stay the same, and what had to change.

    uv run scripts/preserve_check.py

Writes results/preserve.csv. Per case task:
    T2 re-fabric   shape_iou against the base photo, dE_mean against the new swatch
    T3 colourways  shape_iou of each output against the line drawing's filled outline, the same
                   reference for every colourway; dE_mean against its own swatch
    T4 recolour    dE of the dark colour against the target hex, dE of the light colour against
                   the base photo's light colour, ssim of luminance against the base photo

The model reframes its output, so shapes are compared after cropping each garment mask to its
bounding box and resizing to a common 256x384 frame. That measures silhouette, not position.
The floor is high: two unrelated garments, the C05 coat and the C02 dress, already score 0.839,
because any full-length garment fills most of its own box. Read shape_iou against that, not 0.
"""

import csv
import re

import cv2
import numpy as np
from skimage.color import deltaE_ciede2000, rgb2lab
from skimage.metrics import structural_similarity

from autocheck import dominant, lab
from lib import RESULTS, case_dir, load_manifest, rel

FRAME = (256, 384)


def grabcut_mask(rgb):
    """Foreground mask by GrabCut, with a 2% border taken as certain background.

    garment_mask's single colour distance from the border fails here in two ways seen in C07:
    a white garment on a light grey ground sits under its threshold, and an output that ignores
    the prompt and puts the garment on a dark vignette makes the border colour meaningless.
    GrabCut models foreground and background colour separately, so neither breaks it.
    """
    h, w = rgb.shape[:2]
    f = 512 / max(h, w)
    small = cv2.resize(rgb, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    b = max(2, int(0.02 * max(sh, sw)))
    mask = np.zeros((sh, sw), np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.setRNGSeed(0)
    cv2.grabCut(cv2.cvtColor(small, cv2.COLOR_RGB2BGR), mask, (b, b, sw - 2 * b, sh - 2 * b), bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    fg = np.isin(mask, (cv2.GC_FGD, cv2.GC_PR_FGD)).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(fg)
    if n > 1:
        fg = (labels == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])).astype(np.uint8)
    return cv2.resize(fg, (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)


def normalised(path):
    """Garment mask and greyscale image, cropped to the garment and resized to FRAME."""
    rgb, img_lab = lab(path)
    mask = grabcut_mask(rgb)
    ys, xs = np.where(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    m = cv2.resize(mask[y0:y1, x0:x1].astype(np.uint8), FRAME, interpolation=cv2.INTER_NEAREST).astype(bool)
    g = cv2.resize(cv2.cvtColor(rgb[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY), FRAME, interpolation=cv2.INTER_AREA)
    return m, g, img_lab[mask]


def drawing_silhouette(path):
    """Filled outer outline of a black-on-white line drawing, cropped and resized to FRAME."""
    g = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    ink = cv2.morphologyEx((g < 128).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    fill = np.zeros_like(ink)
    cv2.drawContours(fill, [max(contours, key=cv2.contourArea)], -1, 1, cv2.FILLED)
    ys, xs = np.where(fill)
    crop = fill[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return cv2.resize(crop, FRAME, interpolation=cv2.INTER_NEAREST).astype(bool)


def iou(a, b):
    return round(float((a & b).sum() / max(1, (a | b).sum())), 3)


def de_mean(swatch, garment_lab):
    sw_c, sw_share = dominant(lab(swatch)[1])
    g_c, _ = dominant(garment_lab[None, :, :])
    d = np.array([[deltaE_ciede2000(a[None, None], b[None, None]).item() for b in g_c] for a in sw_c])
    return round(float((d.min(axis=1) * sw_share).sum()), 1)


def dark_light(garment_lab):
    c, _ = dominant(garment_lab[None, :, :], k=2)
    return c[np.argsort(c[:, 0])]


def hex_lab(h):
    rgb = np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], np.uint8)[None, None]
    return rgb2lab(rgb)[0, 0]


def main():
    rows = []
    for c in load_manifest()["cases"]:
        if c.get("status") != "ready" or c["task"] not in ("T2", "T3", "T4"):
            continue
        d = case_dir(c["id"])
        outs = sorted(RESULTS.glob(f"*/{c['id']}/*.png"))
        if c["task"] == "T2":
            bm, _, _ = normalised(d / "inputs/base_photo.jpg")
            for o in outs:
                om, _, ol = normalised(o)
                rows.append({"case": c["id"], "file": rel(o), "shape_iou": iou(bm, om),
                             "dE_mean": de_mean(d / "inputs/fabric.jpg", ol)})
        elif c["task"] == "T3":
            ref = drawing_silhouette(d / "inputs/line_drawing.png")
            for o in outs:
                k = int(re.search(r"_cw(\d+)_", o.stem).group(1))
                om, _, ol = normalised(o)
                rows.append({"case": c["id"], "file": rel(o), "colourway": k,
                             "shape_iou": iou(ref, om), "dE_mean": de_mean(d / c["colourways"][k - 1], ol)})
        else:
            bm, bg, bl = normalised(d / "inputs/base_photo.jpg")
            base_light = dark_light(bl)[1]
            target = hex_lab(c["target"]["to"])
            for o in outs:
                om, og, ol = normalised(o)
                dark, light = dark_light(ol)
                rows.append({"case": c["id"], "file": rel(o), "shape_iou": iou(bm, om),
                             "dE_dark_vs_target": round(float(deltaE_ciede2000(dark[None, None], target[None, None]).item()), 1),
                             "dE_light_vs_base": round(float(deltaE_ciede2000(light[None, None], base_light[None, None]).item()), 1),
                             "ssim": round(float(structural_similarity(bg, og, data_range=255)), 3)})
    for r in rows:
        print(r)
    if rows:
        fields = list(dict.fromkeys(k for r in rows for k in r))
        with (RESULTS / "preserve.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
