"""Make a case's line drawing by asking the image model to trace the source photo.

    uv run --env-file .env scripts/trace.py C03 --dry-run
    uv run --env-file .env scripts/trace.py C03

Used when edge detection cannot separate seams from the fabric's own pattern. The model sees the
ground-truth photo while tracing, so the drawing is marked synthetic in SOURCES.csv and the
manifest notes record that it was traced from the ground truth.

The edge-detection drawing, if any, is kept as inputs/line_drawing_edges.png for comparison.
"""

import argparse
import base64
import csv
import io
import os
import sys
import time

import cv2
from PIL import Image

from lib import RESULTS, add_source, case_dir, get_case, load_manifest, rel, save_manifest, today
from run import LOG_FIELDS, actual_cost, estimate

PROMPT = (
    "Trace this garment photo into a clean flat technical drawing (fashion flat sketch), front view: "
    "thin uniform black lines on a pure white background. Draw the silhouette, every seam, the hem, "
    "collar and cuffs, buttons, pleats, trims and their exact positions as they appear in the photo. "
    "Do not draw the fabric's print, checks, stripes or texture, and do not shade or fill anything. "
    "Do not draw the mannequin or its stand. Do not add or remove any detail."
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--model", default="gpt-image-2.6-sunburst")
    ap.add_argument("--size", default="1024x1536")
    ap.add_argument("--quality", default="high")
    ap.add_argument("--max-cost", type=float, default=0.25)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    m = load_manifest()
    c = get_case(m, a.case)
    d = case_dir(a.case)
    fx = c["fixture"]
    img = cv2.imread(str(d / fx["source_image"]))
    x, y, w, h = fx["garment_box"]
    crop = Image.fromarray(cv2.cvtColor(img[y:y + h, x:x + w], cv2.COLOR_BGR2RGB))
    crop.thumbnail((1536, 1536))
    est = estimate(a.size, a.quality, 1)
    print(f"trace {a.case}: {crop.size[0]}x{crop.size[1]} crop -> {a.model} {a.size} {a.quality}, est ${est:.3f}")
    if a.dry_run:
        print(f"prompt: {PROMPT}")
        return
    if est > a.max_cost:
        sys.exit(f"est ${est:.3f} exceeds --max-cost ${a.max_cost}")
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set (run with: uv run --env-file .env ...)")

    from openai import OpenAI
    buf = io.BytesIO()
    crop.save(buf, "PNG")
    buf.name = "garment.png"
    buf.seek(0)
    t = time.time()
    res = OpenAI().images.edit(model=a.model, image=[buf], prompt=PROMPT, size=a.size, quality=a.quality, n=1)
    latency = round(time.time() - t, 1)

    out = d / "inputs/line_drawing.png"
    edges = d / "inputs/line_drawing_edges.png"
    if out.exists() and not edges.exists():
        out.rename(edges)
    out.write_bytes(base64.b64decode(res.data[0].b64_json))
    u = res.usage
    cost = actual_cost(u)

    logf = RESULTS / "log.csv"
    RESULTS.mkdir(exist_ok=True)
    new = not logf.exists()
    with logf.open("a", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            wr.writeheader()
        wr.writerow(dict(time=time.strftime("%F %T"), round=0, case=a.case, variant="trace", sample=1,
                         model=a.model, size=a.size, quality=a.quality, latency_s=latency,
                         text_in_tokens=u.input_tokens_details.text_tokens,
                         image_in_tokens=u.input_tokens_details.image_tokens,
                         output_tokens=u.output_tokens, cost_usd=round(cost, 4), cost_source="usage",
                         file=rel(out)))

    src = rel(d / fx["source_image"])
    add_source({"file": rel(out), "case": a.case, "role": "input_drawing", "license": "synthetic (model output)",
                "author": a.model, "title": "line drawing traced from source photo", "retrieved": today(),
                "derived_from": src, "synthetic": "true",
                "notes": f"traced by {a.model} quality={a.quality} from garment_box {fx['garment_box']}; model saw the ground-truth photo"})
    note = "Line drawing traced by the image model from the ground-truth photo (synthetic)."
    if note not in c.get("notes", ""):
        c["notes"] = (c.get("notes", "") + " " + note).strip()
        save_manifest(m)
    print(f"wrote {rel(out)} in {latency}s, ${cost:.4f}")


if __name__ == "__main__":
    main()
