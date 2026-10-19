# open-code-go-optimal-frontier

Which OpenCode Go models give the most capability for their usage limit?

`python3 build.py` regenerates `index.html`: each model's Artificial Analysis
Intelligence Index (y) against requests per 5 hours on the $10/month Go plan
(x, log scale). It also draws a log-linear trend line and the Pareto frontier.

## Where the data comes from

| Data | Source |
|---|---|
| Models and 5h request limits | [opencode.ai/go](https://opencode.ai/go). The page is rendered from `packages/console/app/src/component/go-models.ts` in [anomalyco/opencode](https://github.com/anomalyco/opencode), and its server render only lists the "featured" models, so the script reads that file first (raw GitHub, then a sparse `git clone`) and scrapes the live page as a cross-check. The last good fetch is cached in `data/go-models.cache.json`. |
| Capability | Artificial Analysis Intelligence Index v4.3.x. If `ARTIFICIAL_ANALYSIS_API_KEY` is set, scores come live from the AA API, matched by `aa_slug`. Otherwise they come from `data/capabilities.json`, where each score was researched by hand and lists its source. |

A model with no AA score can carry a `benchmarks` object in
`data/capabilities.json` (for example `{"gpqa": 88, "swe_bench": 71}`). The
script then fits each benchmark against AA scores across the models that have
both, and turns those fits into an AA-equivalent score. That needs at least 3
reference models per benchmark. Otherwise you can set `aa_index` by hand with
`"type": "estimated"`, as Hy4 preview does.

## Analysis

- **Trend:** OLS fit of `score = a + b·log10(requests)`. The model's residual is its distance from this line.
- **Pareto frontier:** a model is on the frontier if no other model has both at least as many requests and at least as high a score.
- Free promotional models with unlimited requests are listed but not plotted.

```
python3 build.py            # fetch everything and rebuild index.html
python3 build.py --offline  # use the cached model list
```
