"""Generate images for every ready case.

    uv run scripts/run.py --dry-run                         # list planned calls and estimated cost, no API
    uv run scripts/run.py --cases C03 --samples 1           # one image, end to end
    uv run scripts/run.py --model gpt-image-2.6-flare --quality low --max-cost 0.5

Reads OPENAI_API_KEY from the environment. Never sends ground_truth/.
Outputs: results/<model>/<case>/<variant>_r<round>_s<n>.png, log in results/log.csv.
Existing outputs are skipped, so re-running resumes.
"""

import argparse
import base64
import csv
import os
import sys
import time

from lib import RESULTS, case_dir, load_manifest, rel

# Standard-tier USD per token, developers.openai.com/api/docs/pricing (checked 2026-11-24).
# Identical for gpt-image-2.6-sunburst and gpt-image-2.6-flare.
PRICE = {"text_in": 5e-6, "image_in": 8e-6, "image_out": 30e-6}
# Output tokens per 1024x1024 image by quality, from OpenAI's calculator; scaled by area.
OUT_TOKENS_1K = {"low": 823, "medium": 1449, "high": 1756}
# Conservative pre-call allowance per input image, used only by the --max-cost guard.
EST_INPUT_USD_PER_IMAGE = 0.015

LOG_FIELDS = ["time", "round", "case", "variant", "sample", "model", "size", "quality",
              "latency_s", "text_in_tokens", "image_in_tokens", "output_tokens",
              "cost_usd", "cost_source", "file", "error"]


def observed():
    """Highest logged cost per (model, size, quality), from calls billed by usage."""
    seen = {}
    logf = RESULTS / "log.csv"
    if logf.exists():
        with logf.open(newline="") as f:
            for r in csv.DictReader(f):
                if r["cost_source"] == "usage":
                    k = (r["model"], r["size"], r["quality"])
                    seen[k] = max(seen.get(k, 0.0), float(r["cost_usd"]))
    return seen


def estimate(size, quality, n_inputs, model=None, seen=None):
    """Pre-call cost for the --max-cost guard.

    Uses the highest cost already logged for this model, size and quality plus 20% headroom,
    since input tokens vary with the inputs. Falls back to the output-token table plus a fixed
    allowance per input image, which runs about 2x high.
    """
    if seen and (model, size, quality) in seen:
        return seen[(model, size, quality)] * 1.2
    w, h = map(int, size.split("x"))
    out = OUT_TOKENS_1K[quality] * (w * h) / (1024 * 1024)
    return out * PRICE["image_out"] + n_inputs * EST_INPUT_USD_PER_IMAGE


def actual_cost(usage):
    d = usage.input_tokens_details
    return (d.text_tokens * PRICE["text_in"] + d.image_tokens * PRICE["image_in"]
            + usage.output_tokens * PRICE["image_out"])


def build_prompt(m, c):
    fields = {k: c.get(k, "") for k in ("item", "scale_note", "recolor", "motif_name", "placement", "detail")}
    return " ".join(m["prompt_template"][c["task"]].format(**fields).split())


def plan(m, a):
    jobs = []
    for c in m["cases"]:
        if c.get("status") != "ready" or (a.cases and c["id"] not in a.cases):
            continue
        d = case_dir(c["id"])
        inputs = [d / p for p in c["inputs"]]
        assert not any("ground_truth" in str(p) for p in inputs), f"{c['id']}: ground truth in inputs"
        for s in range(1, a.samples + 1):
            out = RESULTS / a.model / c["id"] / f"{a.variant}_r{a.round}_s{s}.png"
            jobs.append(dict(case=c["id"], inputs=inputs, prompt=build_prompt(m, c), sample=s, out=out))
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="*")
    ap.add_argument("--model", default="gpt-image-2.6-sunburst")
    ap.add_argument("--size", default="1024x1536")
    ap.add_argument("--quality", default="medium", choices=list(OUT_TOKENS_1K))
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--variant", default="A", help="A = drawing/photo + swatch in one edit call")
    ap.add_argument("--max-cost", type=float, default=5.0, help="USD budget for this invocation")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    m = load_manifest()
    jobs = plan(m, a)
    todo = [j for j in jobs if not j["out"].exists()]
    seen = observed()
    est = sum(estimate(a.size, a.quality, len(j["inputs"]), a.model, seen) for j in todo)
    print(f"{len(jobs)} jobs, {len(jobs) - len(todo)} already done, {len(todo)} to run, "
          f"est ${est:.2f} (budget ${a.max_cost:.2f})")

    if a.dry_run:
        for j in jobs:
            state = "done" if j["out"].exists() else "todo"
            print(f"  {state} {j['case']} s{j['sample']} -> {rel(j['out'])}")
            print(f"       inputs: {', '.join(rel(p) for p in j['inputs'])}")
        if jobs:
            print(f"\nprompt ({jobs[0]['case']}): {jobs[0]['prompt']}")
        return

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("OPENAI_API_KEY is not set")
    from openai import OpenAI
    client = OpenAI(api_key=key)

    logf = RESULTS / "log.csv"
    RESULTS.mkdir(exist_ok=True)
    new = not logf.exists()
    spent = 0.0
    with logf.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        for j in todo:
            next_est = estimate(a.size, a.quality, len(j["inputs"]), a.model, seen)
            if spent + next_est > a.max_cost:
                print(f"stop: spent ${spent:.3f}, next call est ${next_est:.3f} would exceed --max-cost")
                break
            j["out"].parent.mkdir(parents=True, exist_ok=True)
            row = dict(time=time.strftime("%F %T"), round=a.round, case=j["case"], variant=a.variant,
                       sample=j["sample"], model=a.model, size=a.size, quality=a.quality)
            t = time.time()
            files = [open(p, "rb") for p in j["inputs"]]
            try:
                res = client.images.edit(model=a.model, image=files, prompt=j["prompt"],
                                         size=a.size, quality=a.quality, n=1)
                j["out"].write_bytes(base64.b64decode(res.data[0].b64_json))
                u = res.usage
                cost = actual_cost(u)
                row.update(text_in_tokens=u.input_tokens_details.text_tokens,
                           image_in_tokens=u.input_tokens_details.image_tokens,
                           output_tokens=u.output_tokens, cost_usd=round(cost, 4),
                           cost_source="usage", file=rel(j["out"]))
            except Exception as e:  # log and continue; one bad case should not stop the run
                cost = next_est  # assume billed, so the guard stays conservative
                row.update(cost_usd=round(cost, 4), cost_source="estimate", error=repr(e)[:300])
            finally:
                for fh in files:
                    fh.close()
            spent += cost
            row["latency_s"] = round(time.time() - t, 1)
            w.writerow(row)
            f.flush()
            print(f"{'ERR ' if row.get('error') else 'ok  '}{j['case']} s{j['sample']} "
                  f"{row['latency_s']}s ${row['cost_usd']} {row.get('error', '')}")
    print(f"spent ${spent:.3f}")


if __name__ == "__main__":
    main()
