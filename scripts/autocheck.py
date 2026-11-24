"""Automatic checks for patterned cases (checks, stripes, colourways).

    uv run scripts/autocheck.py            # every generated image of every case with "autocheck": true

Writes results/autocheck.csv with, per image:
    dE_mean / dE_max   CIEDE2000 between the swatch's k dominant colours and the nearest garment colour
    repeat_axis        "across" (rows) or "down" (columns), from case.scale.repeat.axis
    period_px          dominant repeat period along that axis (autocorrelation)
    repeats            measured extent / period_px
    repeats_vs_truth   repeats / the ground truth's repeats (1.0 = same scale, < 1 = pattern too large)

Garment pixels are found by distance from the background colour sampled at the image border,
which holds for the plain backgrounds the prompt asks for.
"""

import csv

import cv2
import numpy as np
from skimage.color import deltaE_ciede2000, rgb2lab

from lib import RESULTS, case_dir, load_manifest, rel

K = 4


def lab(path):
    rgb = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
    return rgb, rgb2lab(rgb)


def dominant(lab_px, k=K):
    cv2.setRNGSeed(0)  # k-means++ seeding is random; fixed so reruns give the same numbers
    data = lab_px.reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, labels, centres = cv2.kmeans(data, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    share = np.bincount(labels.ravel(), minlength=k) / len(labels)
    return centres, share


def garment_mask(lab_img):
    h, w, _ = lab_img.shape
    border = np.concatenate([lab_img[:8].reshape(-1, 3), lab_img[-8:].reshape(-1, 3),
                             lab_img[:, :8].reshape(-1, 3), lab_img[:, -8:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    mask = (deltaE_ciede2000(lab_img, bg[None, None, :]) > 8).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n < 2:
        return mask.astype(bool)
    return labels == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])


def repeat_period(grey, mask, axis="across", band=(1 / 3, 2 / 3)):
    """Median dominant repeat period, in px, and the extent it was measured over.

    axis "across" takes rows, "down" takes columns. Lines are limited to a band of the garment's
    height, given as fractions from the top: the middle third by default, or a band the case
    names (case.scale.repeat.band), e.g. the underskirt of a dress whose bodice is draped.
    Columns through a whole garment cross hems, waistbands and trims, and that structure swamps
    the fabric's repeat, so "down" needs a band free of them.

    Each line is blurred at a scale proportional to its length, so pinstripes and weave do not
    register as the repeat, and the strongest autocorrelation peak between 1/30 and 1/2 of the
    line length wins.
    """
    ys = np.where(mask.any(axis=1))[0]
    y0, y1 = ys.min() + int(np.ptp(ys) * band[0]), ys.min() + int(np.ptp(ys) * band[1])
    if axis == "across":
        lines = (mask[y] for y in range(y0, y1, 4))
        pixels = (grey[y] for y in range(y0, y1, 4))
        extent = np.ptp(np.where(mask[y0:y1].any(axis=0))[0])
    else:
        xs = np.where(mask[y0:y1].any(axis=0))[0]
        cols = range(xs.min(), xs.max(), 4)
        lines = (np.r_[np.zeros(y0, bool), mask[y0:y1, x]] for x in cols)
        pixels = (grey[:y1, x] for x in cols)
        extent = y1 - y0
    periods = []
    for m_line, g_line in zip(lines, pixels):
        idx = np.where(m_line)[0]
        if len(idx) < 64:
            continue
        line = g_line[idx.min():idx.max()].astype(float)
        line = cv2.GaussianBlur(line[None, :], (0, 0), max(2.0, len(line) / 100)).ravel()
        line -= line.mean()
        ac = np.correlate(line, line, "full")[len(line) - 1:]
        ac /= ac[0] + 1e-9
        lo, hi = max(6, len(line) // 30), len(line) // 2
        if hi <= lo + 2:
            continue
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] > 0.15 and lo < lag < hi - 1:
            periods.append(lag)
    return (float(np.median(periods)) if periods else None), int(extent)


def check(case, swatch, out, box=None):
    _, sw_lab = lab(swatch)
    sw_c, sw_share = dominant(sw_lab)
    rgb, img_lab = lab(out)
    if box:  # ground truth: restrict to the garment so the mannequin and stand are not measured
        x, y, w, h = box
        rgb, img_lab = rgb[y:y + h, x:x + w], img_lab[y:y + h, x:x + w]
    mask = garment_mask(img_lab)
    g_c, _ = dominant(img_lab[mask][None, :, :])
    d = np.array([[deltaE_ciede2000(a[None, None], b[None, None]).item() for b in g_c] for a in sw_c])
    nearest = d.min(axis=1)
    grey = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    rep = (case.get("scale") or {}).get("repeat") or {}
    axis = rep.get("axis", "across")
    period, extent = repeat_period(grey, mask, axis, tuple(rep.get("band", (1 / 3, 2 / 3))))
    return {
        "case": case["id"], "file": rel(out),
        "dE_mean": round(float((nearest * sw_share).sum()), 1), "dE_max": round(float(nearest.max()), 1),
        "repeat_axis": axis, "period_px": period,
        "repeats": round(extent / period, 1) if period else "",
    }


def main():
    m = load_manifest()
    rows = []
    for c in m["cases"]:
        if not c.get("autocheck") or c.get("status") != "ready":
            continue
        swatch = case_dir(c["id"]) / "inputs/fabric.jpg"
        refs = [("ground_truth", p) for p in sorted((case_dir(c["id"]) / "ground_truth").glob("*.jpg"))]
        outs = [("output", p) for p in sorted(RESULTS.glob(f"*/{c['id']}/*.png"))]
        box = (c.get("fixture") or {}).get("garment_box")
        truth = None
        for kind, p in refs + outs:
            r = check(c, swatch, p, box if kind == "ground_truth" else None)
            r["kind"] = kind
            truth = truth or (r if kind == "ground_truth" else None)
            ok = truth and r["repeats"] and truth["repeats"]
            r["repeats_vs_truth"] = round(r["repeats"] / truth["repeats"], 2) if ok else ""
            rows.append(r)
            print(r)
    if rows:
        with (RESULTS / "autocheck.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
