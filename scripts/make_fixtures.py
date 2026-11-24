"""Turn a case's source photo into model inputs and ground truth.

    uv run scripts/make_fixtures.py C03 --preview   # draw the boxes from manifest.json on the photo
    uv run scripts/make_fixtures.py C03             # write inputs/, raw_crops/, ground_truth/, _crop_log.json

Reads case.fixture from manifest.json:
    source_image  path relative to the case dir, e.g. "source/met_159178_0.jpg"
    swatch_box    [x, y, w, h] of a flat, front-on fabric area with as little drape as possible
    garment_box   [x, y, w, h] around the whole garment, used for the line drawing

Museum photos have no grey card, so swatches are kept as published (no white balance).
"""

import argparse
import csv
import json
import shutil

import cv2
import numpy as np

from lib import SOURCES, add_source, case_dir, get_case, load_manifest, rel, today


def crop(img, box):
    x, y, w, h = box
    return img[y:y + h, x:x + w]


def line_drawing(bgr):
    """Black-on-white outline: edges of the garment, small specks removed.

    Pattern edges (checks, stripes) are suppressed by blurring at a scale larger than the
    print, so the drawing keeps seams and silhouette but does not leak the fabric.
    """
    grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    k = max(5, (min(grey.shape) // 120) | 1)
    smooth = cv2.bilateralFilter(cv2.medianBlur(grey, k), 9, 60, 9)
    edges = cv2.Canny(smooth, 30, 90)
    edges = cv2.dilate(edges, np.ones((2, 2), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(edges, connectivity=8)
    keep = np.zeros_like(edges)
    min_len = min(grey.shape) // 40
    for i in range(1, n):
        if max(stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]) >= min_len:
            keep[labels == i] = 255
    return 255 - keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()

    m = load_manifest()
    c = get_case(m, a.case)
    fx = c["fixture"]
    d = case_dir(a.case)
    src = d / fx["source_image"]
    img = cv2.imread(str(src))
    if img is None:
        raise SystemExit(f"cannot read {src}")

    if a.preview:
        out = img.copy()
        for box, colour in ((fx["swatch_box"], (0, 0, 255)), (fx["garment_box"], (0, 200, 0))):
            if box:
                x, y, w, h = box
                cv2.rectangle(out, (x, y), (x + w, y + h), colour, max(2, img.shape[1] // 300))
        fn = d / "_preview.jpg"
        cv2.imwrite(str(fn), out)
        print(f"wrote {rel(fn)}  ({img.shape[1]}x{img.shape[0]})")
        return

    for sub in ("inputs", "raw_crops", "ground_truth"):
        (d / sub).mkdir(exist_ok=True)
    log = {"case": a.case, "source_image": rel(src), "made": today(), "files": {}}
    base = {"case": a.case, "source_url": "", "license": "", "author": "", "title": "", "synthetic": "false"}

    sw = crop(img, fx["swatch_box"])
    for fn in (d / "raw_crops/fabric.jpg", d / "inputs/fabric.jpg"):
        cv2.imwrite(str(fn), sw, [cv2.IMWRITE_JPEG_QUALITY, 95])
    log["files"]["inputs/fabric.jpg"] = {"crop": fx["swatch_box"], "colour_correction": "none (no reference card in source)"}

    # The edge drawing always goes to line_drawing_edges.png. It becomes line_drawing.png only
    # when there is none yet, so a drawing made by trace_drawing.py or by hand is never overwritten.
    ld = line_drawing(crop(img, fx["garment_box"]))
    cv2.imwrite(str(d / "inputs/line_drawing_edges.png"), ld)
    log["files"]["inputs/line_drawing_edges.png"] = {"crop": fx["garment_box"], "method": "median+bilateral blur, Canny 30/90, speck removal"}
    drawing_is_edges = not (d / "inputs/line_drawing.png").exists()
    if drawing_is_edges:
        shutil.copy(d / "inputs/line_drawing_edges.png", d / "inputs/line_drawing.png")
        log["files"]["inputs/line_drawing.png"] = {**log["files"]["inputs/line_drawing_edges.png"], "copy_of": "inputs/line_drawing_edges.png"}
    else:
        prev = d / "_crop_log.json"
        if prev.exists():
            old = json.loads(prev.read_text())["files"].get("inputs/line_drawing.png")
            if old:
                log["files"]["inputs/line_drawing.png"] = old
        print("kept existing inputs/line_drawing.png")

    shutil.copy(src, d / "ground_truth/photo.jpg")
    log["files"]["ground_truth/photo.jpg"] = {"crop": None, "method": "copy of source"}
    (d / "_crop_log.json").write_text(json.dumps(log, indent=2) + "\n")

    with SOURCES.open(newline="") as f:
        parent = next((r for r in csv.DictReader(f) if r["file"] == rel(src)), None)
    if parent:
        base.update({k: parent[k] for k in ("source_url", "license", "author", "title", "object_date")})
    outputs = [("inputs/fabric.jpg", "input_fabric"), ("inputs/line_drawing_edges.png", "reference"),
               ("ground_truth/photo.jpg", "ground_truth")]
    if drawing_is_edges:
        outputs.append(("inputs/line_drawing.png", "input_drawing"))
    for name, role in outputs:
        add_source({**base, "file": rel(d / name), "role": role, "retrieved": today(),
                    "derived_from": rel(src), "notes": json.dumps(log["files"][name])})
        print("wrote", rel(d / name))


if __name__ == "__main__":
    main()
