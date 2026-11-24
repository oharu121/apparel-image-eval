"""Build gallery/index.html from data/ and results/.

    uv run scripts/gallery.py && open gallery/index.html

Two modes:
    Cases  inputs | outputs | ground truth per case, labelled
    Blind  every output shuffled, model/variant hidden, shown beside its inputs and ground truth,
           scored 1-5 on each axis; scores stay in the browser and export as scores.csv
"""

import json

from lib import RESULTS, ROOT, case_dir, load_manifest

AXES = ["silhouette", "fabric_pattern", "pattern_scale", "colour", "texture",
        "construction", "usable_for_planning"]


def main():
    m = load_manifest()
    cases = []
    for c in m["cases"]:
        d = case_dir(c["id"])
        outs = sorted(RESULTS.glob(f"*/{c['id']}/*.png"))
        if not outs and c.get("status") != "ready":
            continue
        cases.append({
            "id": c["id"], "task": c["task"], "item": c["item"], "material": c["material"],
            "inputs": [f"../{p.relative_to(ROOT)}" for p in (d / i for i in c.get("inputs", [])) if p.exists()],
            "truth": [f"../{p.relative_to(ROOT)}" for p in sorted((d / "ground_truth").glob("*")) if p.is_file()],
            "outputs": [{"src": f"../{p.relative_to(ROOT)}", "label": f"{p.parent.parent.name} / {p.stem}"} for p in outs],
        })
    html = TEMPLATE.replace("__DATA__", json.dumps({"cases": cases, "axes": AXES}))
    out = ROOT / "gallery" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html)
    print(f"wrote gallery/index.html: {len(cases)} cases, {sum(len(c['outputs']) for c in cases)} outputs")


TEMPLATE = r"""<!doctype html>
<meta charset="utf-8">
<title>Apparel image eval</title>
<style>
  body { font: 14px/1.4 system-ui, sans-serif; margin: 0 16px 48px; background: #fafafa; color: #222; }
  header { position: sticky; top: 0; background: #fafafa; padding: 12px 0; border-bottom: 1px solid #ddd; z-index: 1; }
  button { font: inherit; padding: 4px 12px; }
  button[aria-pressed=true] { background: #222; color: #fff; }
  section { margin-top: 24px; }
  .row { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-start; }
  figure { margin: 0; background: #fff; border: 1px solid #ddd; padding: 6px; }
  figure img { display: block; max-height: 360px; max-width: 280px; }
  figcaption { font-size: 12px; color: #666; margin-top: 4px; }
  .in { border-style: dashed; } .gt { border-color: #2a6fdb; }
  .scores { display: grid; grid-template-columns: auto repeat(5, 2em); gap: 2px 4px; align-items: center; font-size: 12px; }
  .done { outline: 3px solid #3a3; }
</style>
<header>
  <button id="m-cases" aria-pressed="true">Cases</button>
  <button id="m-blind" aria-pressed="false">Blind scoring</button>
  <button id="export">Export scores.csv</button>
  <span id="status"></span>
</header>
<main id="main"></main>
<script>
const D = __DATA__;
const KEY = "apparel-eval-scores";
let scores = {};
try { scores = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch {}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(scores)); } catch {} status(); };
const fig = (src, cap, cls = "") => `<figure class="${cls}"><a href="${src}" target="_blank"><img src="${src}" loading="lazy"></a><figcaption>${cap}</figcaption></figure>`;
const main = document.getElementById("main");

function status() {
  const total = D.cases.reduce((n, c) => n + c.outputs.length, 0);
  const done = Object.values(scores).filter(s => D.axes.every(a => s[a])).length;
  document.getElementById("status").textContent = ` ${done}/${total} outputs fully scored`;
}

function casesView() {
  main.innerHTML = D.cases.map(c => `<section><h2>${c.id} · ${c.task} · ${c.item} · ${c.material}</h2><div class="row">
    ${c.inputs.map(s => fig(s, "input: " + s.split("/").pop(), "in")).join("")}
    ${c.outputs.map(o => fig(o.src, o.label)).join("")}
    ${c.truth.map(s => fig(s, "ground truth", "gt")).join("")}</div></section>`).join("");
}

function shuffled(xs) {
  const a = xs.slice();
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

function blindView() {
  const items = shuffled(D.cases.flatMap(c => c.outputs.map(o => ({ c, o }))));
  main.innerHTML = items.map(({ c, o }, n) => {
    const s = scores[o.src] || {};
    const grid = D.axes.map(a => `<span>${a}</span>` + [1,2,3,4,5].map(v =>
      `<label><input type="radio" name="${n}-${a}" value="${v}" data-src="${o.src}" data-axis="${a}" ${s[a] == v ? "checked" : ""}></label>`).join("")).join("");
    const full = D.axes.every(a => s[a]) ? "done" : "";
    return `<section><h2>#${n + 1} · ${c.task}</h2><div class="row">
      ${c.inputs.map(x => fig(x, "input", "in")).join("")}
      <figure class="${full}" id="f${n}"><img src="${o.src}"><figcaption>output</figcaption></figure>
      ${c.truth.map(x => fig(x, "ground truth", "gt")).join("")}
      <div class="scores">${grid}</div></div></section>`;
  }).join("");
}

main.addEventListener("change", e => {
  const t = e.target;
  if (!t.dataset.src) return;
  (scores[t.dataset.src] ||= {})[t.dataset.axis] = +t.value;
  save();
  const f = t.closest("section").querySelector("figure:not(.in):not(.gt)");
  f.classList.toggle("done", D.axes.every(a => scores[t.dataset.src][a]));
});

function setMode(blind) {
  document.getElementById("m-cases").setAttribute("aria-pressed", !blind);
  document.getElementById("m-blind").setAttribute("aria-pressed", blind);
  blind ? blindView() : casesView();
}
document.getElementById("m-cases").onclick = () => setMode(false);
document.getElementById("m-blind").onclick = () => setMode(true);
document.getElementById("export").onclick = () => {
  const head = ["file", ...D.axes];
  const rows = Object.entries(scores).map(([src, s]) => [src.replace(/^\.\.\//, ""), ...D.axes.map(a => s[a] ?? "")]);
  const csv = [head, ...rows].map(r => r.join(",")).join("\n") + "\n";
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: "scores.csv" });
  a.click();
};
setMode(false);
status();
</script>
"""

if __name__ == "__main__":
    main()
