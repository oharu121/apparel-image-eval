"""Write REPORT.md and its figures from the manifest, the logs and results/evaluation.json.

    uv run scripts/report.py

Figures follow one colour code: dashed grey frame = input, no frame = output, blue frame = ground
truth. The judgments (what worked, issues, 1-5 scores) are written by hand in
results/evaluation.json; everything else is read from data/ and results/.
"""

import csv
import json
import statistics
from collections import defaultdict

from PIL import Image, ImageDraw, ImageFont

from lib import RESULTS, ROOT, case_dir, load_manifest

FIG = ROOT / "report" / "figures"
H = 520
PAD = 14
LABEL = 30
BLUE = (42, 111, 219)
GREY = (150, 150, 150)
AXES = ["silhouette", "fabric_pattern", "pattern_scale", "colour", "texture", "construction", "usable_for_planning"]


def font(size):
    for name in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def dashed_rect(draw, box, colour, width=3, dash=12):
    x0, y0, x1, y1 = box
    for x in range(x0, x1, dash * 2):
        draw.line([(x, y0), (min(x + dash, x1), y0)], colour, width)
        draw.line([(x, y1), (min(x + dash, x1), y1)], colour, width)
    for y in range(y0, y1, dash * 2):
        draw.line([(x0, y), (x0, min(y + dash, y1))], colour, width)
        draw.line([(x1, y), (x1, min(y + dash, y1))], colour, width)


def strip(case_id, tiles):
    """tiles: list of (path, label, kind, crop_box) with kind in input/output/truth."""
    ims = []
    for path, label, kind, box in tiles:
        im = Image.open(path).convert("RGB")
        if box:
            x, y, w, h = box
            im = im.crop((x, y, x + w, y + h))
        im.thumbnail((int(H * 1.2), H))
        ims.append((im, label, kind))
    width = sum(im.width for im, _, _ in ims) + PAD * (len(ims) + 1)
    out = Image.new("RGB", (width, H + LABEL + PAD * 2), "white")
    d = ImageDraw.Draw(out)
    f = font(17)
    x = PAD
    for im, label, kind in ims:
        y = PAD + (H - im.height) // 2
        out.paste(im, (x, y))
        box = (x - 4, y - 4, x + im.width + 4, y + im.height + 4)
        if kind == "input":
            dashed_rect(d, box, GREY)
        elif kind == "truth":
            d.rectangle(box, outline=BLUE, width=4)
        d.text((x, PAD + H + 8), label, fill=BLUE if kind == "truth" else (40, 40, 40), font=f)
        x += im.width + PAD
    FIG.mkdir(parents=True, exist_ok=True)
    fn = FIG / f"{case_id}.jpg"
    out.save(fn, quality=88)
    return fn.relative_to(ROOT)


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def main():
    m = load_manifest()
    ev = json.loads((RESULTS / "evaluation.json").read_text())
    log = read_csv(RESULTS / "log.csv")
    auto = read_csv(RESULTS / "autocheck.csv")
    cases = [c for c in m["cases"] if c["id"] in ev["cases"]]
    gen = [r for r in log if r["variant"] != "trace" and not r["error"]]
    models = sorted({r["model"] for r in gen})

    L = ["# Apparel image eval: results", ""]
    L += [f"Cases evaluated: {', '.join(c['id'] for c in cases)} of {len(m['cases'])} planned. "
          f"Models: {', '.join(f'`{x}`' for x in models)}. Reviewer: {ev['reviewer']}.", ""]

    L += ["## 1. Summary", ""] + [f"- {s}" for s in ev["summary"]] + [""]

    L += ["## 2. Test dataset", "",
          "Each case starts from a public-domain museum photo of a real garment. The model gets a line drawing "
          "and a fabric swatch made from that photo; the photo itself is the ground truth and is never sent.", "",
          "| Case | Task | Garment | Fabric | Ground truth | Source |", "|---|---|---|---|---|---|"]
    for c in cases:
        L.append(f"| {c['id']} | {c['task']} | {c['item']} | {c['material']} | {', '.join(c['ground_truth'])} | {c['source']} |")
    L += ["", "Licences, authors and derivations for every file are in [data/SOURCES.csv](data/SOURCES.csv).", ""]

    L += ["## 3. Method", "",
          "| | |", "|---|---|",
          "| API | OpenAI `POST /v1/images/edits`, all inputs in one call |",
          f"| Models | {', '.join(f'`{x}`' for x in models)} |",
          f"| Settings | {', '.join(sorted({r['quality'] + ' quality, ' + r['size'] for r in gen}))} |",
          "| Prompt | One template per task type, filled only from the case's item and scale fields; no per-case tuning in round 1 (templates in [data/manifest.json](data/manifest.json)) |",
          "| Samples | 3 per case x model x variant. The API has no seed, so samples are independent draws |",
          "| Variant A | line drawing + fabric swatch → product photo |",
          "| Auto-checks | CIEDE2000 between the swatch's 4 dominant colours and the garment's; pattern repeat count by autocorrelation along the case's repeat axis, compared with the ground truth's |",
          "| Scoring | 1-5 on " + ", ".join(AXES) + " |", ""]
    notes = [c for c in cases if c.get("notes")]
    if notes:
        L += ["Input notes that affect the results:", ""] + [f"- **{c['id']}**: {c['notes']}" for c in notes] + [""]

    L += ["## 4. Results by case", "",
          "Dashed grey frame = input, no frame = output, blue frame = ground truth.", ""]
    for c in cases:
        d = case_dir(c["id"])
        tiles = [(d / p, "Input: " + p.split("/")[-1].split(".")[0].replace("_", " "), "input", None) for p in c["inputs"]]
        outs = sorted(RESULTS.glob(f"*/{c['id']}/*.png"))
        tiles += [(p, f"{p.parent.parent.name.replace('gpt-image-', '')} {p.stem}", "output", None) for p in outs]
        box = (c.get("fixture") or {}).get("garment_box")
        tiles += [(d / p, "Ground truth", "truth", box) for p in c["ground_truth"]]
        fig = strip(c["id"], tiles)
        e = ev["cases"][c["id"]]
        L += [f"### {c['id']} · {c['task']} · {c['material']}", "", f"![{c['id']}]({fig})", ""]
        L += ["**What worked**", ""] + [f"- {s}" for s in e["worked"]] + [""]
        L += ["**Issues**", ""] + [f"- {s}" for s in e["issues"]] + [""]
        rows = [r for r in auto if r["case"] == c["id"]]
        if rows:
            L += [f"| Image | ΔE mean | ΔE max | Repeats {rows[0]['repeat_axis']} | vs ground truth |", "|---|---|---|---|---|"]
            for r in rows:
                L.append(f"| {r['file'].split('/')[-1]} | {r['dE_mean']} | {r['dE_max']} | {r['repeats']} | {r['repeats_vs_truth']} |")
            L += [""]
        sc = e.get("scores", {})
        if sc:
            L += ["| Image | " + " | ".join(a.replace("_", " ") for a in AXES) + " |", "|---" * (len(AXES) + 1) + "|"]
            for f, s in sc.items():
                L.append(f"| {f.split('/')[-1]} | " + " | ".join(str(s[a]) for a in AXES) + " |")
            L.append("| **median** | " + " | ".join(str(statistics.median(s[a] for s in sc.values())) for a in AXES) + " |")
            L += [""]

    L += ["## 5. Cost and latency", "",
          "Cost per call is computed from the response's `usage` tokens at standard-tier prices "
          "($5 / 1M text input, $8 / 1M image input, $30 / 1M image output).", "",
          "| Step | Model | Quality, size | Calls | Mean cost | Mean latency | Total |", "|---|---|---|---|---|---|---|"]
    groups = defaultdict(list)
    for r in log:
        if not r["error"]:
            groups[("drawing trace" if r["variant"] == "trace" else f"variant {r['variant']}, round {r['round']}",
                    r["model"], f"{r['quality']}, {r['size']}")].append(r)
    total = 0.0
    for (step, model, qs), rs in groups.items():
        costs = [float(r["cost_usd"]) for r in rs]
        total += sum(costs)
        L.append(f"| {step} | `{model}` | {qs} | {len(rs)} | ${statistics.mean(costs):.4f} | "
                 f"{statistics.mean(float(r['latency_s']) for r in rs):.1f}s | ${sum(costs):.3f} |")
    L += ["", f"Total spent: **${total:.3f}**. Per-call rows are in [results/log.csv](results/log.csv).", ""]

    (ROOT / "REPORT.md").write_text("\n".join(L))
    print(f"wrote REPORT.md and {len(cases)} figure(s), total ${total:.3f}")


if __name__ == "__main__":
    main()
