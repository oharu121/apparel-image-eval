"""Find and download public-domain garments from The Met Open Access.

    uv run scripts/fetch_met.py search plaid            # list candidates, PD status checked per object
    uv run scripts/fetch_met.py get C03 12345           # download object 12345 as the source photo for case C03
    uv run scripts/fetch_met.py get C03 12345 --primary-only
    uv run scripts/fetch_met.py get C01 12345 --image 1993.42ab.jpg   # one specific view

images.metmuseum.org serves scripts a bot challenge, so download the image in a browser, save it
as data/cases/<case>/source/met_<id>_0.jpg, and run get --primary-only: existing files are not
re-downloaded, and the metadata and SOURCES.csv row are still written.

The search endpoint's isPublicDomain filter is not reliable (it returns objects whose own
record says isPublicDomain: false), so every object is re-checked before it is used.
"""

import argparse
import json
import sys
import time

import requests

from lib import add_source, case_dir, rel, today

API = "https://collectionapi.metmuseum.org/public/collection"
COSTUME_DEPT = 8
UA = {"User-Agent": "apparel-image-eval (personal research)"}


def get_json(url, params=None, tries=4):
    for i in range(tries):
        r = requests.get(url, params=params, headers=UA, timeout=30)
        if r.ok and r.headers.get("Content-Type", "").startswith("application/json"):
            return r.json()
        time.sleep(2 * (i + 1))  # Imperva throttles bursts with an HTML page
    raise RuntimeError(f"{url}: HTTP {r.status_code} {r.headers.get('Content-Type')}")


def obj(object_id):
    """The object record, or None when the search index lists an ID the object endpoint 404s."""
    r = requests.get(f"{API}/v1/objects/{object_id}", headers=UA, timeout=30)
    if r.status_code == 404:
        return None
    return get_json(f"{API}/v1/objects/{object_id}")


def search(q, limit, any_department=False):
    params = {"hasImages": "true", "isPublicDomain": "true", "q": q, "limit": limit}
    if not any_department:
        params["departmentId"] = COSTUME_DEPT
    res = get_json(f"{API}/v1.1/search", params)
    print(f"{res['total']} hits for {q!r}; checking first {len(res['objectIDs'])}")
    for oid in res["objectIDs"]:
        o = obj(oid)
        if o is None:
            print(f"--  {oid:>7}  (listed by search, 404 from the object endpoint)")
            continue
        pd ="PD " if o["isPublicDomain"] and o["primaryImage"] else "-- "
        print(f"{pd}{oid:>7}  {o['department'][:20]:20}  {o['objectDate'][:16]:16}  {o['title'][:40]:40}  "
              f"+{len(o['additionalImages'])} imgs  {o['objectURL']}")
        time.sleep(0.3)


def get(case_id, object_id, primary_only, image=None):
    o = obj(object_id)
    if o is None:
        sys.exit(f"object {object_id} not found")
    if not o["isPublicDomain"] or not o["primaryImage"]:
        sys.exit(f"object {object_id} is not public domain or has no image; refusing")
    d = case_dir(case_id) / "source"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"met_{object_id}.json").write_text(json.dumps(o, indent=2, ensure_ascii=False))
    urls = [o["primaryImage"]] + o["additionalImages"]
    if image:
        picks = [i for i, u in enumerate(urls) if u.rsplit("/", 1)[-1] == image]
        if not picks:
            sys.exit(f"{image} is not one of object {object_id}'s images: {[u.rsplit('/', 1)[-1] for u in urls]}")
    else:
        picks = [0] if primary_only else range(len(urls))
    for i in picks:
        url = urls[i]
        fn = d / f"met_{object_id}_{i}.jpg"
        if not fn.exists():
            r = requests.get(url, headers=UA, timeout=60)
            r.raise_for_status()
            if not r.headers.get("Content-Type", "").startswith("image/"):
                sys.exit(f"{url}: got {r.headers.get('Content-Type')} instead of an image "
                         "(images.metmuseum.org serves a bot challenge to scripts); "
                         f"download it in a browser and save it as {rel(fn)}")
            fn.write_bytes(r.content)
            time.sleep(0.3)
        add_source({
            "file": rel(fn), "case": case_id, "role": "source_photo",
            "source_url": o["objectURL"], "license": "CC0 1.0 (The Met Open Access)",
            "author": o["artistDisplayName"] or o["creditLine"], "title": o["title"],
            "object_date": o["objectDate"], "retrieved": today(), "synthetic": "false",
            "notes": f"image {i} of {len(urls)}: {url}",
        })
        print("saved", rel(fn))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("q")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--any-department", action="store_true", help="search beyond the Costume Institute")
    g = sub.add_parser("get")
    g.add_argument("case")
    g.add_argument("object_id", type=int)
    g.add_argument("--primary-only", action="store_true", help="skip the additional views")
    g.add_argument("--image", help="only this view, by the filename the Met serves it under")
    a = ap.parse_args()
    search(a.q, a.limit, a.any_department) if a.cmd == "search" else get(a.case, a.object_id, a.primary_only, a.image)


if __name__ == "__main__":
    main()
