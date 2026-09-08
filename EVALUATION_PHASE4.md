# Phase 4: Paint-equivalent path batching

## Rule

Only consecutive paint-order entries with identical fill, stroke, opacity,
fill-rule, and transform state are considered. A batch is split if the new
painted bbox intersects any existing batch bbox after a 1px antialias margin.
Each region's existing `M...Z` geometry is concatenated unchanged into the
compound path, retaining `fill-rule="evenodd"`.

Across all five inputs, the ordered geometry string, expanded fill stream, and
expanded style stream are exactly identical before and after batching. Region
count, subpaths, path commands, vertices, ordering, and underlap are unchanged.

## Results

| Test | Paths before | Paths after | Reduction | SVG before | SVG after | Rasterize before | Rasterize after | Render diff mean / max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| test_1 | 45,861 | 5,398 | 88.23% | 6,699,149 | 3,468,941 | 3.253s | 1.398s | 0.00438 / 7 |
| test_2 | 44,595 | 5,413 | 87.86% | 6,658,781 | 3,530,892 | 3.620s | 1.580s | 0.00349 / 12 |
| test_3 | 39,668 | 5,058 | 87.25% | 5,928,469 | 3,174,404 | 3.144s | 1.425s | 0.00288 / 8 |
| test_4 | 15,272 | 3,570 | 76.62% | 2,546,475 | 1,635,033 | 1.419s | 0.820s | 0.00077 / 12 |
| test_5 | 41,668 | 5,267 | 87.36% | 6,166,817 | 3,263,986 | 3.028s | 1.457s | 0.00312 / 8 |

Five-illustration arithmetic means:

- path reduction: 85.46%
- SVG file-size reduction: 44.90%
- CairoSVG rasterization improvement: 52.44%
- total-runtime improvement: 17.42%
- baseline-vs-batched render mean absolute delta: 0.00293/255

The renders are not byte-identical. Cairo computes antialias coverage once for
a compound fill but composites separate elements independently. This affects
0.51% of pixels on average, with extremely small channel deltas. Geometry and
style streams are exact, and visual inspection found no crack, hole, bleed,
layering, or missing-detail regression.

## Batch distribution

The five illustrations produced 24,706 paths: 9,079 singleton, 6,034 with 2–4
regions, 6,196 with 5–16, 3,257 with 17–64, and 140 with 65 or more. Maximum
batch size was 114.

## Verdict

**BATCHING_HIGHLY_EFFECTIVE.** Element count and rasterization time exceed the
success thresholds while preserving the exact ordered geometry/style stream.

The next single variable to evaluate is the batch-overlap safety margin,
currently fixed at 1px.
