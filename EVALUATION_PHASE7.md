# Phase 7: Strict 32-color parity vs VTracer 1.0

## Identity and configuration

No stable VTracer 1.0 release existed at evaluation time, so the comparison
used the latest official 1.0-series prebuilt Windows CLI from
[`1.0.0-alpha.4`](https://github.com/visioncortex/vtracer/releases/tag/1.0.0-alpha.4)
of [`visioncortex/vtracer`](https://github.com/visioncortex/vtracer).

- version: `vtracer 1.0.0-alpha.4`
- license: MIT OR Apache-2.0
- release asset SHA-256: `8eadb5529864265f003f791ad9cb128e1b9b8b8af8c21016f38b04706bcf3531`
- extracted binary SHA-256: `185c20424a5eed31f2ed0caf9d72b6cc7ae86480bab05199fd5cbde55d4b40b1`

LayerTrace settings were unchanged from Phase 6: 32 colors, simplify 1.0,
containment ordering, 1px underlap, curve fitting off, consecutive batching,
and 1px batch safety margin.

VTracer used its 1.0 defaults explicitly: color-cluster, stacked, spline,
speckle 4, color precision 6, gradient step 16, path precision 2, optimize 1,
plus the sole comparison variable `--max-colors 32`. No rescue condition or
parameter sweep was used.

Both vectorization runtimes are medians of three runs from input load through
SVG write; VTracer includes process startup. Both SVGs were rasterized three
times with the same CairoSVG, white background, RGB mode, and source dimensions.

## Color parity

LayerTrace emitted exactly 32 distinct fill colors for every image. VTracer
emitted 32, 30, 31, 31, and 31 respectively. The mean was 32 versus 31, so the
large Phase 6 palette-count confound was removed. No gradients, strokes, or
inherited colors increased the count beyond the requested maximum.

## Results

| Test | Visual winner | LT fills | VT fills | LT MAE | VT MAE | LT SVG | VT SVG | LT paths | VT paths | LT runtime | VT runtime |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| test_1 | VTracer | 32 | 32 | 3.902 | 2.522 | 3,469,182 | 277,733 | 5,398 | 592 | 3.972s | 0.381s |
| test_2 | VTracer | 32 | 30 | 3.618 | 3.109 | 3,531,276 | 325,646 | 5,413 | 628 | 4.119s | 0.440s |
| test_3 | VTracer | 32 | 31 | 3.594 | 3.074 | 3,174,725 | 292,437 | 5,058 | 575 | 4.083s | 0.401s |
| test_4 | VTracer | 32 | 31 | 7.710 | 5.837 | 1,635,308 | 470,215 | 3,570 | 850 | 1.748s | 0.624s |
| test_5 | VTracer | 32 | 31 | 4.097 | 3.253 | 3,264,462 | 357,108 | 5,267 | 751 | 3.808s | 0.459s |

Averages:

- actual fills: LayerTrace 32.0, VTracer 31.0
- MAE: LayerTrace 4.584, VTracer 3.559
- SVG size: LayerTrace 3,014,991 bytes, VTracer 344,628 bytes
- paths: LayerTrace 4,941, VTracer 679
- path commands: LayerTrace 315,171, VTracer 13,316
- vectorization: LayerTrace 3.546s, VTracer 0.461s
- rasterization: LayerTrace 1.006s, VTracer 0.137s

At color parity, VTracer remained about 7.7× faster, used 7.3× fewer paths,
produced 8.7× smaller SVGs, and used 23.7× fewer path commands. LayerTrace's
paths were line-based under its current default; VTracer's output was
cubic-based and contained no polygon or group elements.

## Visual inspection

- test_1: VTracer preserved the face, smooth silhouette, and hair shape with
  less edge stippling.
- test_2: VTracer retained separated hair locks, hair tips, eye shapes, and
  thin outlines more cleanly.
- test_3: VTracer kept the blue-gray layers structurally distinct and retained
  subtle skin colors with lower error.
- test_4: VTracer kept the character separated from the window, plant, and
  shelf while producing much cleaner clothing and hair regions.
- test_5: VTracer retained sparkles, hair highlights, clothing highlights, and
  small eye details with far fewer paths.

No visible crack advantage was found for LayerTrace. Both stacked renders were
gap-free in the inspected images.

## Questions

- **A. Color parity:** achieved; 32 versus 30–32 actual fills.
- **B. Visual fidelity:** VTracer remained better on all five images.
- **C. Structural efficiency:** VTracer's advantage remained very large.
- **D. Runtime:** VTracer remained substantially faster, even including process
  startup.
- **E. Posterization character:** LayerTrace retained a harsher, noisier fixed-
  palette texture, but it was not a quality or structural advantage at parity.

The MAE gap narrowed from Phase 6's 4.584 versus 2.691 to 4.584 versus 3.559,
but VTracer still won visual quality, structure, and runtime simultaneously.

## Decision

**VTRACER_STILL_CLEARLY_BETTER**

Color count was the last major known confound, and removing it did not reverse
any primary result. VTracer remained the stronger implementation across every
fixed image and every primary metric.

## Final conclusion

**B. LayerTrace should close as a research PoC; using VTracer as the baseline
and implementation is more rational.**

LayerTrace successfully tested explicit underlap and conservative paint-order
batching, but strict parity provides no evidence that continuing a separate
general vectorizer would outperform the mature baseline.
