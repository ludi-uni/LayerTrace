# Phase 3: Algorithmic efficiency and curve representation

## Profile

The baseline `test_1` cProfile top stages were SVG rasterization (9841 ms),
small-region merge (2473 ms), and region extraction/metadata/contours (1707 ms).
Connected-component calls themselves were only 361 ms. Bbox-local underlap was
310 ms, so raster dilation was retained; a vector offset would add hole and
self-intersection complexity without attacking the measured bottleneck.

The stage timings in this report came from local cProfile artifacts, which are
generated under the ignored `out/` directory and are not part of the public
source tree. Peak memory was left unreported because Python tracemalloc would
exclude the dominant OpenCV/Cairo native allocations.

## Changes

- Replaced 32 palette-sized full-raster boolean scans with one indexed RGB LUT.
- Retained compact bbox-local region masks, contour extraction, and dilation;
  no region allocates a full-frame mask.
- Serialized line paths compactly.
- Added optional corner-aware least-squares cubic fitting with Newton
  reparameterization and recursive error subdivision.
- Preserved sharp/short contours as lines. Only contours with at least 128
  simplified points are considered, and a cubic is retained only when it
  reduces both serialized bytes and command count.
- Added shape, contour, on-curve vertex, path command, line, cubic, control
  point, and SVG byte metrics plus `--curve-fit` / `--curve-error`.

No region was removed, merged by a new rule, or reordered. Shared-edge and
topology reconstruction remain absent.

## Five-image benchmark

| Test | Runtime before | Runtime after | SVG before | SVG after | Commands before | Commands after | MAE change |
|---|---:|---:|---:|---:|---:|---:|---:|
| test_1 | 12.054 s | 8.858 s | 7,007,880 | 6,699,149 | 365,951 | 365,759 | +0.079% |
| test_2 | 11.113 s | 8.976 s | 6,974,046 | 6,658,781 | 372,771 | 372,532 | +0.023% |
| test_3 | 9.697 s | 8.636 s | 6,209,337 | 5,928,469 | 335,424 | 335,185 | +0.332% |
| test_4 | 4.115 s | 4.167 s | 2,682,034 | 2,546,475 | 159,429 | 159,189 | +0.015% |
| test_5 | 10.935 s | 8.659 s | 6,455,869 | 6,166,817 | 342,280 | 341,995 | +0.101% |

Across the five illustrations, mean runtime improved from 9.583 s to 7.859 s
(17.98%), mean SVG size fell 4.53%, and mean MAE rose only 0.092%. Shapes were
unchanged. Mean command count fell only 0.076%; 363 cubic commands were adopted
across the five images. Visual inspection found no obvious new crack, layering
failure, or missing detail.

The 30% command target was not reached. Tens of thousands of tiny paths each
require at least a move and close command, so the representation is dominated
by region count rather than long polygonal contours.

## Conclusion

**USEFUL_OPTIMIZATION.** Runtime improves clearly on the intended five-image
set and SVGs are consistently smaller with negligible visual/metric change,
but curve fitting cannot materially reduce commands while region explosion
dominates the document.

The main remaining bottleneck is **region explosion**, because it drives SVG
shape count and CairoSVG draw overhead even after contour representation is
compressed.

The next single variable to improve is same-color consecutive-region path
batching, measured strictly for paint-order equivalence before adoption.
