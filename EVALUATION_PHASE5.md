# Phase 5: Batch safety margin evaluation

## Scope

The Phase 4 algorithm was held fixed while `batch_safety_margin` alone varied
over 0, 0.5, 1, and 2 pixels. Colors, simplification, containment ordering,
underlap, cubic fitting, same-style consecutive batching, bbox overlap logic,
and `evenodd` fill remained unchanged. The five committed regression images
were evaluated. A previously deleted optional stress asset was unavailable and
was not restored.

## Aggregate results

| Margin | Mean paths | Path reduction | Mean SVG bytes | Rasterize | Render delta vs 1px | Changed pixels | Visual safety |
|---:|---:|---:|---:|---:|---:|---:|---|
| 0px | 4,172.6 | 87.51% | 2,936,394 | 1,168.97ms | 0.000224/255 | 0.0367% | no visible regression |
| 0.5px | 4,566.4 | 86.48% | 2,976,541 | 1,183.65ms | 0.000112/255 | 0.0188% | no visible regression |
| 1px | 4,941.2 | 85.46% | 3,014,651 | 1,195.02ms | 0 | 0 | baseline |
| 2px | 5,677.6 | 83.53% | 3,088,859 | 1,228.90ms | 0.000198/255 | 0.0340% | no visible regression |

Relative to 1px, 0px produced 15.6% fewer paths, a 2.6% smaller SVG, 2.2%
faster CairoSVG rasterization, and 0.5% lower total runtime. All 20 runs kept
the same region count and exact ordered geometry/style streams. The maximum
0px channel delta was 8/255; differences were isolated antialias compositing
pixels rather than geometry, fill, hole, or ordering changes.

## Largest observed delta location per image

- test_1: margin 0, `(109, 802)`, flat blue background beside the left silhouette.
- test_2: margin 0, `(477, 811)`, jaw / hair-shadow boundary.
- test_3: margin 2, `(887, 157)`, upper-right blue-gray background boundary.
- test_4: margin 0, `(828, 432)`, fine hair boundary near the face and eye.
- test_5: margin 0, `(879, 148)`, blue background beside upper-right hair/highlights.

Focused inspection found no unexpected holes, missing hair locks, background
intersection failure, sparkle loss, new seam, color bleed, or layering change.

## Verdict

**KEEP_1PX_MARGIN.** Zero margin gives a meaningful additional element
reduction, and exact bbox overlap is still rejected, so the five-image geometry
remains safe. However, its downstream gain is only about 2.6% in SVG size,
2.2% in rasterization, and 0.5% in total runtime. The required optional stress
input was unavailable, so the evidence is not strong enough to replace the
established 1px public default.

The largest remaining bottleneck is repeated preprocessing and region
construction for each serialization variant, not the batch safety margin.
