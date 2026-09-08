# LayerTrace final research conclusion

## Status

**RESEARCH COMPLETE / ARCHIVED**

LayerTrace is concluded as a research proof of concept. It will not continue as
an independent general-purpose raster-to-vector implementation. VTracer is the
recommended baseline and practical implementation for future vectorization
work.

## Research question

Can useful SVG approximations of flat illustrations be generated without
shared-edge topology, watertight subdivision, or junction reconstruction by
using a back-to-front paint stack with controlled underlap?

## What worked

- A 1px underlap substantially reduced visible cracks compared with zero
  underlap across the five-image fixed evaluation set.
- Paint-order-aware batching of consecutive same-style regions reduced SVG
  element count by roughly 85% and CairoSVG rasterization time by roughly 52%
  without changing ordered geometry or style streams.
- A deterministic fixed palette produced a consistent posterized appearance.
- The method retained the broad color-field structure of simple cel-style
  illustrations.

## What did not differentiate

- Stacked back-to-front vectorization was already a known and implemented
  technique in VTracer.
- Cubic fitting alone had little effect because thousands of short connected
  regions, rather than long contours, dominated LayerTrace's output.
- Conservative batching improved LayerTrace substantially but did not approach
  VTracer's already compact SVG structure.
- Both implementations produced gap-free stacked renders on the fixed set, so
  the explicit underlap control did not establish a practical crack-suppression
  advantage over VTracer.
- LayerTrace did not establish a general vectorization quality, speed, or
  structural-efficiency advantage.

## Phase 1–5 findings

The initial PoC confirmed that independent regions could be painted with
underlap without constructing shared boundaries. The five-image expansion then
identified 1px as the reliable underlap setting and exposed region explosion as
the dominant cost. Bbox-local processing and compact path representation
improved runtime, while long-contour cubic fitting yielded only minor command
reductions. Consecutive same-style batching was the strongest LayerTrace-side
optimization. A later safety-margin evaluation found that smaller margins could
batch more paths, but the downstream runtime and file-size gains were too small
to displace the established 1px default without broader evidence.

## Comparison with VTracer

Phase 6 compared LayerTrace with official VTracer 0.6.4 stacked defaults.
VTracer clearly won visual fidelity, structure, and runtime, although the
comparison was confounded by VTracer using hundreds of fitted colors.

Phase 7 removed that confound with the official VTracer 1.0.0-alpha.4
`--max-colors 32` mode. Actual fill counts were LayerTrace 32 and VTracer 30–32.
The five-image means were:

| Metric | LayerTrace | VTracer |
|---|---:|---:|
| MAE | 4.584 | 3.559 |
| SVG size | 3,014,991 bytes | 344,628 bytes |
| path elements | 4,941 | 679 |
| path commands | 315,171 | 13,316 |
| vectorization runtime | 3.546 s | 0.461 s |
| rasterization runtime | 1.006 s | 0.137 s |

VTracer remained the visual winner on all five images. It was approximately
7.7× faster, used 7.3× fewer paths, produced 8.7× smaller SVGs, and used 23.7×
fewer path commands. The archived comparison data and per-image artifacts are
in [`docs/benchmarks/phase7`](benchmarks/phase7/).

## Final decision

> **LayerTrace is concluded as a research PoC.**
>
> **VTracer is the recommended implementation for general-purpose
> raster-to-vector conversion.**

The strict color-parity comparison removed the last major known confounding
factor and did not reverse any primary result. Continuing a separate generic
vectorizer is therefore not justified by the evidence collected here.

## Future direction

Reopening LayerTrace should require a clearly different objective rather than
another attempt at general vectorization. Plausible archive-derived directions
are limited to:

- deterministic fixed-palette posterization;
- a preprocessing frontend for an established vectorizer;
- educational or experimental visualization of paint stacks and underlap.

None of these directions is implemented or active in this closeout.
