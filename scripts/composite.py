"""Build inputs/composite.png: the swatch tiled at true scale inside the line drawing's outline.

    uv run scripts/composite.py C02 C03

Variant E gives the model the pattern's scale as an image instead of as words. The swatch was
cut from the same photo as the ground truth, so its pixels share the ground truth's scale; the
drawing is at another scale, so the swatch is resized by

    s = drawing outline extent / ground-truth garment extent

along the axis the case's repeat is measured on (case.scale.repeat.axis: "across" = width,
"down" = height), and tiled across the outline, with the drawing's lines multiplied back on top.
One ratio cannot serve both axes, because a traced drawing does not keep the photo's
proportions: for C03 the width ratio is 0.393 and the height ratio 0.471. Using the measured
axis keeps the composite and autocheck.py on the same footing. Only that ratio is taken from the
ground truth; the ground-truth image itself is never sent.
"""

import json
import sys

import cv2
import numpy as np

from autocheck import garment_mask, lab
from lib import add_source, case_dir, get_case, load_manifest, rel, today


def outline(drawing_grey):
    ink = cv2.morphologyEx((drawing_grey < 128).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    fill = np.zeros_like(ink)
    cv2.drawContours(fill, [max(contours, key=cv2.contourArea)], -1, 1, cv2.FILLED)
    return fill.astype(bool)


def build(case_id):
    m = load_manifest()
    c = get_case(m, case_id)
    d = case_dir(case_id)
    drawing = cv2.imread(str(d / "inputs/line_drawing.png"))
    grey = cv2.cvtColor(drawing, cv2.COLOR_BGR2GRAY)
    fill = outline(grey)
    axis = ((c.get("scale") or {}).get("repeat") or {}).get("axis", "across")
    k = 0 if axis == "across" else 1  # any(axis=0) gives columns, so its extent is the width
    dh = np.ptp(np.where(fill.any(axis=k))[0])

    x, y, w, h = c["fixture"]["garment_box"]
    _, truth_lab = lab(d / "ground_truth/photo.jpg")
    gmask = garment_mask(truth_lab[y:y + h, x:x + w])
    gh = np.ptp(np.where(gmask.any(axis=k))[0])
    s = dh / gh

    sw = cv2.imread(str(d / "inputs/fabric.jpg"))
    tile = cv2.resize(sw, (max(1, round(sw.shape[1] * s)), max(1, round(sw.shape[0] * s))), interpolation=cv2.INTER_AREA)
    H, W = grey.shape
    reps = (H // tile.shape[0] + 1, W // tile.shape[1] + 1, 1)
    texture = np.tile(tile, reps)[:H, :W]

    out = np.full_like(drawing, 255)
    out[fill] = texture[fill]
    lines = (grey.astype(np.float32) / 255.0)[..., None]
    out = (out.astype(np.float32) * lines).astype(np.uint8)
    fn = d / "inputs/composite.png"
    cv2.imwrite(str(fn), out)

    log_file = d / "_crop_log.json"
    log = json.loads(log_file.read_text())
    log["files"]["inputs/composite.png"] = {
        "method": "swatch tiled inside the line drawing's filled outline, lines multiplied on top",
        "scale": round(float(s), 4), "axis": axis, "drawing_extent_px": int(dh), "truth_extent_px": int(gh),
        "tile_px": [int(tile.shape[1]), int(tile.shape[0])],
    }
    log_file.write_text(json.dumps(log, indent=2) + "\n")
    add_source({"file": rel(fn), "case": case_id, "role": "input_composite", "license": "derived from CC0 inputs",
                "title": "swatch composited onto the line drawing at true scale", "retrieved": today(),
                "derived_from": f"{rel(d / 'inputs/line_drawing.png')}; {rel(d / 'inputs/fabric.jpg')}",
                "synthetic": "true", "notes": f"scale {s:.4f} = drawing {dh}px / ground truth {gh}px, measured {axis}"})
    print(f"wrote {rel(fn)}: scale {s:.3f} {axis} (drawing {dh}px / truth {gh}px), tile {tile.shape[1]}x{tile.shape[0]}")


if __name__ == "__main__":
    for case_id in sys.argv[1:]:
        build(case_id)
