# Phase 6: VTracer baseline comparison

## Identity and fairness

The comparison used the official
[`visioncortex/vtracer`](https://github.com/visioncortex/vtracer) Windows binary
from release [`0.6.4`](https://github.com/visioncortex/vtracer/releases/tag/0.6.4):

- binary version: `visioncortex VTracer 0.6.4`
- license: MIT OR Apache-2.0
- binary SHA-256: `4ad8d35e566cd15caf582063b8349bd082b8fa2bd461e99d116fc63ad8fdeca0`

LayerTrace used 32 colors, simplify 1.0, containment ordering, 1px underlap,
curve fitting off (the current default), consecutive batching, and 1px batch
safety margin. VTracer used its explicit 0.6.4 defaults: color, stacked,
spline, speckle 4, color precision 6, gradient step 16, corner 60, segment
length 4, splice 45, and path precision 2.

Vectorization timings are medians of three runs from input load through SVG
write. VTracer additionally includes process startup. Rasterization is excluded
and measured separately with the same CairoSVG version, source dimensions, and
RGB conversion for both methods.

VTracer default output used 587–904 explicit fills, while LayerTrace was fixed
to 32. One permitted auxiliary condition changed only VTracer color precision
to 2; it collapsed the images to one or two paths with MAE 36.7–46.3 and was
rejected as an invalid 32-color approximation. No further tuning was performed.

## Main results

| Test | Visual winner | LT MAE | VT MAE | LT SVG | VT SVG | LT paths | VT paths | LT runtime | VT runtime |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| test_1 | VTracer | 3.902 | 2.302 | 3,469,182 | 368,729 | 5,398 | 630 | 4.002s | 0.374s |
| test_2 | VTracer | 3.618 | 2.454 | 3,531,276 | 431,337 | 5,413 | 702 | 4.164s | 0.423s |
| test_3 | VTracer | 3.594 | 2.642 | 3,174,725 | 392,000 | 5,058 | 624 | 4.028s | 0.386s |
| test_4 | VTracer | 7.710 | 3.135 | 1,635,308 | 635,642 | 3,570 | 941 | 1.752s | 0.571s |
| test_5 | VTracer | 4.097 | 2.925 | 3,264,462 | 470,074 | 5,267 | 814 | 3.776s | 0.441s |

Averages:

- MAE: LayerTrace 4.584, VTracer 2.691
- SVG size: LayerTrace 3,014,991 bytes, VTracer 459,556 bytes
- paths: LayerTrace 4,941, VTracer 742
- path commands: LayerTrace 315,171, VTracer 13,312
- vectorization: LayerTrace 3.545s, VTracer 0.439s
- rasterization: LayerTrace 1.012s, VTracer 0.141s

VTracer was about 8.1× faster, used 6.7× fewer paths, produced 6.6× smaller
SVGs, and used 23.7× fewer path commands. Both outputs used paths rather than
polygons or groups. LayerTrace's current default emitted line commands;
VTracer used 9,475–16,344 curve commands per image.

## Visual findings

- test_1: VTracer preserved smooth face, hair, and silhouette transitions with
  less stippling.
- test_2: VTracer retained detached hair locks, eye detail, and thin hair edges
  more cleanly.
- test_3: VTracer preserved adjacent blue-gray regions and subtle facial color
  transitions better.
- test_4: VTracer was substantially more stable across the window, plant,
  shelf, clothing, and face. This was the largest MAE gap.
- test_5: VTracer preserved sparkles, hair highlights, and clothing highlights
  with fewer noisy micro-shapes.
- Neither method showed a clear visible crack or gap on the five images. This
  comparison therefore does not demonstrate an empirical underlap advantage.

## Classification

| Finding | Classification |
|---|---|
| stacked back-to-front painting | KNOWN_EXISTING_TECHNIQUE |
| hierarchical color clustering and speckle filtering | KNOWN_EXISTING_TECHNIQUE |
| spline/curve fitting for compact output | VTRACER_ADVANTAGE |
| path count, commands, SVG size, and runtime | VTRACER_ADVANTAGE |
| visual fidelity on all five fixed images | VTRACER_ADVANTAGE |
| explicit fixed 32-color posterization | LAYERTRACE_ADVANTAGE |
| explicit raster underlap control | LAYERTRACE_SPECIFIC; empirical advantage INCONCLUSIVE |
| safe consecutive same-style path batching | LAYERTRACE_SPECIFIC |

## Where VTracer is clearly better

1. Visual fidelity and fine-detail retention on all five images.
2. SVG structural compactness: paths, commands, and bytes.
3. Vectorization and downstream rasterization speed.

## Where LayerTrace is clearly better

1. Predictable, explicit 32-color posterization in the tested stable-version
   comparison. VTracer 0.6.4's color precision is not a max-color control.

Underlap and batching remain implementation differences, but this experiment
does not show them beating VTracer's default stacked result.

## Already-known ideas

LayerTrace independently recreated stacked painting, hierarchical color-region
construction, speckle filtering, contour simplification, and curve-oriented SVG
representation. VTracer already implements mature forms of these ideas.

## Potentially LayerTrace-specific ideas

- explicit pixel underlap as a user-controlled crack-suppression mechanism
- paint-equivalent consecutive style batching with an overlap safety margin
- explicit region/order/evaluation metadata around the paint stack

## Main conclusion

**LAYERTRACE_HAS_NARROW_DIFFERENTIATION.** The core stacked-vectorization idea
is established prior art, and VTracer 0.6.4 is clearly superior on the fixed
test set. LayerTrace's remaining differentiation is narrow: controlled palette
posterization, explicit underlap semantics, and conservative paint-order-aware
batching. None is shown here to outweigh VTracer's maturity.

## Next step

Evaluate one exact palette-cardinality variable: VTracer 1.0's `--max-colors 32`
against LayerTrace's fixed 32-color output, without changing either geometry
pipeline.
