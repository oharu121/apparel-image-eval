"""Checks for cases without a ground truth: what had to stay the same, and what had to change.

    uv run scripts/preserve_check.py

Writes results/preserve.csv. Per case task:
    T2 re-fabric   shape_iou against the base photo, dE_mean against the new swatch
    T3 colourways  shape_iou of each output against the same sample of colourway 1,
                   dE_mean against its own swatch
    T4 recolour    dE of the dark colour against the target hex, dE of the light colour against
                   the base photo's light colour, ssim of luminance against the base photo

The model reframes its output, so shapes are compared after cropping each garment mask to its
bounding box and resizing to a common 256x384 frame. That measures silhouette, not position.
The floor is high: two unrelated garments, the C05 coat and the C02 dress, already score 0.743,
because any full-length garment fills most of its own box. Read shape_iou against that, not 0.
"""

import csv
import re

import cv2
import numpy as np
from skimage.color import deltaE_ciede2000, rgb2lab
from skimage.metrics import structural_similarity

from autocheck import dominant, garment_mask, lab
from lib import RESULTS, case_dir, load_manifest, rel

FRAME = (256, 384)


def normalised(path):
    """Garment mask and greyscale image, cropped to the garment and resized to FRAME."""
    rgb, img_lab = lab(path)
    mask = garment_mask(img_lab)
    ys, xs = np.where(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    m = cv2.resize(mask[y0:y1, x0:x1].astype(np.uint8), FRAME, interpolation=cv2.INTER_NEAREST).astype(bool)
    g = cv2.resize(cv2.cvtColor(rgb[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY), FRAME, interpolation=cv2.INTER_AREA)
    return m, g, img_lab[mask]


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
            ref = {}
            for o in outs:
                k, s = map(int, re.search(r"_cw(\d+)_r\d+_s(\d+)", o.stem).groups())
                om, _, ol = normalised(o)
                if k == 1:
                    ref[s] = om
                rows.append({"case": c["id"], "file": rel(o), "colourway": k,
                             "shape_iou": iou(ref[s], om) if s in ref else "",
                             "dE_mean": de_mean(d / c["colourways"][k - 1], ol)})
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
