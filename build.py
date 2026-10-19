#!/usr/bin/env python3
"""Build index.html: OpenCode Go ($10/mo plan) capability vs. requests-per-5h frontier.

Pipeline
  1. Models + 5h request limits  <- opencode.ai/go
       The /go page is rendered from go-models.ts in the opencode repo. Its server
       render only shows "featured" models (the rest sit behind an expand toggle),
       so the source file is read first for the full list and the live page is
       scraped as a cross-check / fallback.
  2. Capability                  <- Artificial Analysis Intelligence Index
       Live from the AA API when ARTIFICIAL_ANALYSIS_API_KEY is set, otherwise
       from data/capabilities.json (researched values, each with a source).
       Models with no AA score but other benchmarks get an AA-equivalent score
       from a per-benchmark linear fit against models that have both.
  3. Trend + frontier            <- y = a + b*log10(requests) OLS fit; Pareto set
                                    = no other model has >= requests AND >= score.
  4. Render                      -> index.html (self-contained, no dependencies)

Usage: python3 build.py [--offline] [--out index.html]
"""

import argparse
import datetime as dt
import html
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
GO_PAGE = "https://opencode.ai/go"
SOURCE_PATH = "packages/console/app/src/component/go-models.ts"
SOURCE_RAW = "https://raw.githubusercontent.com/anomalyco/opencode/dev/" + SOURCE_PATH
SOURCE_GIT = "https://github.com/anomalyco/opencode"
AA_API = "https://artificialanalysis.ai/api/v2/data/llms/models"
CAPS_FILE = os.path.join(ROOT, "data", "capabilities.json")
CACHE_FILE = os.path.join(ROOT, "data", "go-models.cache.json")
UA = {"User-Agent": "Mozilla/5.0 (go-frontier build script)"}


def log(msg):
    print(msg, file=sys.stderr)


def http_get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- 1. models

def parse_go_models_ts(src):
    """Pull each `{ id: ..., requests: ... }` object out of the goModels array."""
    start = src.index("export const goModels")
    end = src.index("].sort(", start)
    body = src[start:end]
    models = []
    for obj in re.findall(r"\{[^{}]*\}", body, re.S):
        fields = dict(re.findall(r'(\w+):\s*("[^"]*"|-?[\d.]+|Infinity|true|false)', obj))
        if "id" not in fields:
            continue

        def val(v):
            if v.startswith('"'):
                return v[1:-1]
            if v in ("true", "false"):
                return v == "true"
            return math.inf if v == "Infinity" else float(v)

        m = {k: val(v) for k, v in fields.items()}
        models.append({
            "id": m["id"],
            "name": m["name"],
            "requests": m["requests"],
            "allowance": m.get("allowance"),
            "bonus": m.get("bonus"),
            "limitedTime": bool(m.get("limitedTime")),
            "featured": bool(m.get("featured")),
        })
    return models


def fetch_source():
    try:
        return http_get(SOURCE_RAW), SOURCE_RAW
    except Exception as e:
        log(f"  raw GitHub fetch failed ({e}); trying git sparse clone")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                        SOURCE_GIT, tmp], check=True, env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"})
        subprocess.run(["git", "-C", tmp, "sparse-checkout", "set", os.path.dirname(SOURCE_PATH)], check=True)
        with open(os.path.join(tmp, SOURCE_PATH)) as f:
            return f.read(), SOURCE_GIT + " (git)"


def scrape_go_page():
    """Featured rows from the server-rendered /go page: name + Go requests per 5h."""
    page = http_get(GO_PAGE)
    rows = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        name = re.search(r"<bdi[^>]*>(.*?)</bdi>", row, re.S)
        nums = re.findall(r'data-slot="number"[^>]*>\s*<span[^>]*>(.*?)</span>', row, re.S)
        if not name or not nums:
            continue
        text = re.sub(r"<s>.*?</s>", "", nums[0])  # drop crossed-out pre-bonus value
        text = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
        digits = re.sub(r"[^\d]", "", text)
        rows[html.unescape(name.group(1)).strip()] = float(digits) if digits else math.inf
    return rows


def load_models(offline):
    models, source = None, None
    if not offline:
        try:
            src, source = fetch_source()
            models = parse_go_models_ts(src)
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            with open(CACHE_FILE, "w") as f:
                json.dump({"source": source, "fetched": dt.datetime.now(dt.timezone.utc).isoformat(),
                           "models": [{**m, "requests": None if m["requests"] == math.inf else m["requests"]}
                                      for m in models]}, f, indent=2)
        except Exception as e:
            log(f"  could not fetch go-models.ts: {e}")
        try:
            page = scrape_go_page()
            log(f"  scraped {len(page)} featured rows from {GO_PAGE}")
            if models is None and page:
                models = [{"id": re.sub(r"[^a-z0-9.]+", "-", n.lower()), "name": n, "requests": r,
                           "allowance": None, "bonus": None, "limitedTime": False, "featured": True}
                          for n, r in page.items()]
                source = GO_PAGE + " (featured rows only)"
            elif models:
                by_name = {m["name"]: m for m in models}
                for n, r in page.items():
                    if n in by_name and by_name[n]["requests"] != r:
                        log(f"  page/source mismatch for {n}: page {r} vs source {by_name[n]['requests']}; using page")
                        by_name[n]["requests"] = r
        except Exception as e:
            log(f"  could not scrape {GO_PAGE}: {e}")
    if models is None:
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        models = [{**m, "requests": math.inf if m["requests"] is None else m["requests"]} for m in cache["models"]]
        source = cache["source"] + f" (cached {cache['fetched'][:10]})"
    log(f"  {len(models)} models from {source}")
    return models, source


# ---------------------------------------------------------------- 2. capability

def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def fetch_aa_live(caps):
    key = os.environ.get("ARTIFICIAL_ANALYSIS_API_KEY")
    if not key:
        return 0
    try:
        data = json.loads(http_get(AA_API, {"x-api-key": key}))["data"]
    except Exception as e:
        log(f"  AA API failed: {e}")
        return 0
    by_slug = {m.get("slug"): m for m in data}
    by_name = {norm(m.get("name", "")): m for m in data}
    hits = 0
    for c in caps.values():
        m = by_slug.get(c.get("aa_slug")) or by_name.get(norm(c.get("aa_name", "")))
        score = m and (m.get("evaluations") or {}).get("artificial_analysis_intelligence_index")
        if score is not None:
            c.update(aa_index=score, type="official AA (live API)", sources=[AA_API])
            hits += 1
    log(f"  AA API: refreshed {hits} scores")
    return hits


def fill_estimates(caps):
    """AA-equivalent score from other benchmarks: per-benchmark OLS vs. models with both."""
    benches = {b for c in caps.values() for b in (c.get("benchmarks") or {})}
    fits = {}
    for b in benches:
        pts = [(c["benchmarks"][b], c["aa_index"]) for c in caps.values()
               if c.get("aa_index") is not None and b in (c.get("benchmarks") or {})]
        if len(pts) >= 3:
            fits[b] = ols([p[0] for p in pts], [p[1] for p in pts])
    for c in caps.values():
        if c.get("aa_index") is None and c.get("benchmarks"):
            preds = [fits[b][0] + fits[b][1] * v for b, v in c["benchmarks"].items() if b in fits]
            if preds:
                c["aa_index"] = round(sum(preds) / len(preds), 1)
                c["type"] = "estimated from " + ", ".join(b for b in c["benchmarks"] if b in fits)


# ---------------------------------------------------------------- 3. analysis

def ols(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def analyse(points):
    lx = [math.log10(p["requests"]) for p in points]
    a, b = ols(lx, [p["score"] for p in points])
    ss_res = sum((p["score"] - (a + b * x)) ** 2 for p, x in zip(points, lx))
    my = sum(p["score"] for p in points) / len(points)
    r2 = 1 - ss_res / sum((p["score"] - my) ** 2 for p in points)
    for p, x in zip(points, lx):
        p["residual"] = round(p["score"] - (a + b * x), 2)
        p["pareto"] = not any(q is not p and q["requests"] >= p["requests"] and q["score"] >= p["score"]
                              and (q["requests"] > p["requests"] or q["score"] > p["score"]) for q in points)
    return {"a": a, "b": b, "r2": r2}


# ---------------------------------------------------------------- 4. render

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use cached model list, no network")
    ap.add_argument("--out", default=os.path.join(ROOT, "index.html"))
    args = ap.parse_args()

    log("models:")
    models, model_source = load_models(args.offline)
    log("capability:")
    with open(CAPS_FILE) as f:
        caps_doc = json.load(f)
    caps = caps_doc["models"]
    if not args.offline:
        fetch_aa_live(caps)
    fill_estimates(caps)

    points, excluded = [], []
    for m in models:
        c = caps.get(m["id"]) or {}
        if m["requests"] == math.inf:
            excluded.append({"name": m["name"], "reason": "unlimited (free promo), no finite limit to plot"})
        elif c.get("aa_index") is None:
            excluded.append({"name": m["name"], "reason": c.get("note") or "no capability score found"})
        else:
            points.append({"id": m["id"], "name": m["name"], "requests": m["requests"],
                           "score": c["aa_index"], "type": c.get("type", ""), "variant": c.get("aa_name", ""),
                           "sources": c.get("sources", []), "note": c.get("note", ""),
                           "bonus": m.get("bonus"), "limitedTime": m.get("limitedTime")})
    fit = analyse(points)
    log(f"  plotted {len(points)}, excluded {len(excluded)}; trend score = {fit['a']:.1f} + "
        f"{fit['b']:.2f}*log10(req), R^2={fit['r2']:.2f}; Pareto: "
        + ", ".join(p["name"] for p in sorted(points, key=lambda p: p["requests"]) if p["pareto"]))

    payload = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "modelSource": model_source,
        "capSource": caps_doc.get("description", ""),
        "points": points, "excluded": excluded, "fit": fit,
    }
    with open(os.path.join(ROOT, "template.html")) as f:
        page = f.read().replace("/*__DATA__*/null", json.dumps(payload).replace("</", "<\\/"))
    with open(args.out, "w") as f:
        f.write(page)
    log(f"wrote {args.out}")


if __name__ == "__main__":
    main()
